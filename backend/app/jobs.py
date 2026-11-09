"""Trabajos de análisis en memoria. El token vive solo dentro del hilo del trabajo y se descarta al terminar."""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from . import config
from .analyzer import engine
from .git_ops import GitError, clone_repo, guess_production_branch, ls_remote, privacy_from_probe, scrub
from .models import AnalysisRequest, JobStatus, Platform, Privacy, Report
from .providers import PROVIDERS, UrlError, parse_repo


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = JobStatus(id=self.id, status="queued", stage="En cola", progress=0, log=[])
        self.report: Optional[Report] = None
        self.created = time.time()
        self.lock = threading.Lock()

    def update(self, stage: str, pct: int, msg: str = "") -> None:
        with self.lock:
            self.status.stage = stage
            self.status.progress = max(self.status.progress, pct)
            if msg:
                self.status.log.append(msg)
                self.status.log = self.status.log[-60:]


JOBS: dict[str, Job] = {}
_sem = threading.Semaphore(2)    # máximo 2 análisis simultáneos


def _gc() -> None:
    now = time.time()
    for k in [k for k, j in JOBS.items() if now - j.created > config.JOB_TTL_SECONDS]:
        JOBS.pop(k, None)


def start(req: AnalysisRequest) -> Job:
    _gc()
    job = Job()
    JOBS[job.id] = job
    token = req.token.get_secret_value() if req.token else None
    t = threading.Thread(target=_run, args=(job, req, token), daemon=True)
    t.start()
    return job


def _run(job: Job, req: AnalysisRequest, token: Optional[str]) -> None:
    dest: Optional[Path] = None
    with _sem:
        try:
            with job.lock:
                job.status.status = "running"
            job.update("Validando origen", 3, "Validando el enlace y la plataforma…")
            prov, parsed = parse_repo(req.url, req.platform)

            job.update("Validando origen", 8, f"Plataforma: {prov.label}. Comprobando acceso…")
            anon = ls_remote(parsed, None)
            privacy = privacy_from_probe(anon)
            info = anon
            if not anon.reachable:
                if not token:
                    raise GitError("El repositorio es privado o el enlace no existe: se requiere un token de solo lectura.")
                info = ls_remote(parsed, token)
                if not info.reachable:
                    raise GitError("No se pudo acceder con el token indicado (verifique el permiso de lectura y que el repositorio exista). "
                                   + (info.error or ""))
                privacy = Privacy.private
            elif token:
                token = None        # repo público: no hace falta credencial; se descarta de inmediato

            branch = req.branch or None
            assumed = False
            if branch:
                if branch not in info.branches:
                    raise GitError(f"La rama «{branch}» no existe en el repositorio. Ramas disponibles: {', '.join(info.branches[:12])}")
            else:
                branch, reason = guess_production_branch(info.branches, info.default_branch, parsed.branch_hint)
                if not branch:
                    raise GitError("No se pudo determinar la rama. Indíquela manualmente.")
                assumed = "Indicada en el enlace" not in reason
                job.update("Validando origen", 12, f"Rama de producción: {branch}. {reason}")

            job.update("Clonando", 15, f"Descargando «{branch}» (solo lectura, con historial para medir autoría)…")
            dest = config.WORK_DIR / job.id
            cl = clone_repo(parsed, branch, token, dest)
            token = None            # ya no se necesita
            job.update("Clonando", 28, f"Commit {cl.sha[:8]} descargado" + ("" if cl.has_history else " (sin historial: no se medirá la autoría)") + ".")

            meta = dict(url=parsed.web_url, platform=prov.platform, platform_label=prov.label, owner=parsed.owner, repo=parsed.repo,
                        branch=branch, branch_assumed=assumed, privacy=privacy, sha=cl.sha, date=cl.date, message=cl.message,
                        blob_url_template=prov.blob_template(parsed), has_history=cl.has_history)
            report = engine.analyze_directory(dest, meta, job.update, ai=req.ai_enrichment)
            job.report = report
            with job.lock:
                job.status.status = "done"
                job.status.progress = 100
                job.status.stage = "Listo"
            job.update("Listo", 100, "Análisis completo. El clon temporal fue eliminado.")
        except (UrlError, GitError) as exc:
            with job.lock:
                job.status.status = "error"
                job.status.error = scrub(str(exc), token)
        except Exception as exc:     # error inesperado: no exponer detalles internos
            with job.lock:
                job.status.status = "error"
                job.status.error = f"Error inesperado durante el análisis ({type(exc).__name__}). Intente de nuevo o reporte el caso."
        finally:
            token = None
            if dest:
                shutil.rmtree(dest, ignore_errors=True)       # el código del cliente no se conserva
