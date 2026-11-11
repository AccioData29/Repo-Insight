"""API de Repo Insight."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, export_html, jobs
from .analyzer import enrich
from .export import to_markdown
from .git_ops import GitError, guess_production_branch, ls_remote, privacy_from_probe
from .models import (AnalysisRequest, JobStatus, Platform, Privacy, Report, SourceRequest, SourceValidation)
from .providers import PROVIDERS, UrlError, parse_repo

app = FastAPI(title="Repo Insight", version="1.0.0")


@app.get("/api/config")
def get_config() -> dict:
    return {
        "ai_available": enrich.available(),
        "html_export_available": export_html.available(),
        "platforms": [{"id": p.platform.value, "label": p.label, "analysis_supported": p.analysis_supported}
                      for p in PROVIDERS.values()],
    }


@app.post("/api/source/validate", response_model=SourceValidation)
def validate_source(req: SourceRequest) -> SourceValidation:
    """Valida enlace ↔ plataforma, detecta privacidad real y dice qué permiso se necesita (sin clonar)."""
    try:
        prov, parsed = parse_repo(req.url, req.platform)
    except UrlError as exc:
        return SourceValidation(valid=False, errors=[str(exc)])

    token = req.token.get_secret_value() if req.token else None
    base = SourceValidation(valid=True, platform=prov.platform, platform_label=prov.label,
                            analysis_supported=prov.analysis_supported, owner=parsed.owner, repo=parsed.repo,
                            normalized_url=parsed.web_url)
    try:
        anon = ls_remote(parsed, None)
    except GitError as exc:
        base.errors.append(str(exc))
        return base

    base.privacy_detected = privacy_from_probe(anon)
    info = anon
    if not anon.reachable:
        if base.privacy_detected == Privacy.unknown:
            base.errors.append(anon.error or "No fue posible comprobar el repositorio.")
            return base
        base.needs_token = True
        base.permission = prov.permission_help(parsed)
        if not token:
            base.messages.append("No es accesible sin credenciales: es privado o el enlace no existe. "
                                 "Entregue un token de solo lectura (ver instrucciones).")
            if req.privacy == Privacy.public:
                base.messages.append("Usted indicó «público», pero la plataforma exige credenciales: se tratará como privado.")
            return base
        info = ls_remote(parsed, token)
        if not info.reachable:
            base.errors.append("El token no permite leer el repositorio (permiso insuficiente, expirado, o el repositorio no existe).")
            return base
        base.privacy_detected = Privacy.private
        base.messages.append("Token válido con acceso de lectura.")
    else:
        base.permission = prov.permission_help(parsed)
        base.permission.needed = False
        base.messages.append("Repositorio público: no se requiere ningún permiso.")
        if req.privacy == Privacy.private:
            base.messages.append("Usted indicó «privado», pero es accesible sin credenciales: se tratará como público.")

    base.accessible = True
    base.branches = info.branches[:200]
    base.default_branch = info.default_branch
    base.production_branch, base.production_branch_reason = guess_production_branch(info.branches, info.default_branch, parsed.branch_hint)
    return base


@app.post("/api/analyses", response_model=JobStatus)
def create_analysis(req: AnalysisRequest) -> JobStatus:
    job = jobs.start(req)
    return job.status


@app.get("/api/analyses/{job_id}", response_model=JobStatus)
def get_status(job_id: str) -> JobStatus:
    job = jobs.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Análisis no encontrado o expirado.")
    return job.status


@app.get("/api/analyses/{job_id}/report", response_model=Report)
def get_report(job_id: str) -> Report:
    job = jobs.JOBS.get(job_id)
    if not job or not job.report:
        raise HTTPException(404, "Informe no disponible.")
    return job.report


@app.get("/api/analyses/{job_id}/export.md", response_class=PlainTextResponse)
def export_md(job_id: str) -> PlainTextResponse:
    job = jobs.JOBS.get(job_id)
    if not job or not job.report:
        raise HTTPException(404, "Informe no disponible.")
    r = job.report
    return PlainTextResponse(to_markdown(r), headers={
        "Content-Disposition": f'attachment; filename="informe-{r.meta.repo}.md"'}, media_type="text/markdown; charset=utf-8")


@app.get("/api/analyses/{job_id}/export.html", response_class=HTMLResponse)
def export_html_report(job_id: str) -> HTMLResponse:
    """Informe interactivo en un solo archivo HTML: se abre sin servidor, sin cuenta y sin conexión."""
    job = jobs.JOBS.get(job_id)
    if not job or not job.report:
        raise HTTPException(404, "Informe no disponible.")
    try:
        body = export_html.to_html(job.report)
    except export_html.TemplateMissing as exc:
        raise HTTPException(503, str(exc))
    return HTMLResponse(body, headers={"Content-Disposition": f'attachment; filename="informe-{job.report.meta.repo}.html"'})


# ---- Frontend compilado (despliegue de un solo contenedor) ----
if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        f = (config.FRONTEND_DIST / full_path).resolve()
        if full_path and f.is_file() and config.FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
