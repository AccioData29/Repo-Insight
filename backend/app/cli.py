"""Línea de comandos: genera el informe sin servidor, sin navegador y sin cuentas de terceros.

    python -m app.cli https://github.com/owner/repo --branch main --out informe.html
    GITHUB_TOKEN=... python -m app.cli <url-privada> --token-env GITHUB_TOKEN --out informe.html

El token se lee de una variable de entorno (nunca como argumento, para que no quede en el historial del shell).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import export_html, jobs
from .export import to_markdown
from .models import AnalysisRequest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="repo-insight", description="Analiza un repositorio (solo lectura) y genera el informe.")
    ap.add_argument("url", help="Enlace del repositorio")
    ap.add_argument("--branch", default=None, help="Rama de producción (si se omite, se deduce y se avisa)")
    ap.add_argument("--platform", default=None, help="github | gitlab | azure | bitbucket (si se omite, se detecta)")
    ap.add_argument("--token-env", default=None, help="Nombre de la variable de entorno con el token de solo lectura (repos privados)")
    ap.add_argument("--out", default="informe.html", help="Archivo HTML de salida (por defecto informe.html)")
    ap.add_argument("--md", default=None, help="Además, guardar el informe en Markdown en esta ruta")
    ap.add_argument("--json", default=None, help="Además, guardar el informe en JSON en esta ruta")
    a = ap.parse_args(argv)

    token = os.environ.get(a.token_env) if a.token_env else None
    if a.token_env and not token:
        print(f"La variable de entorno {a.token_env} está vacía o no existe.", file=sys.stderr)
        return 2
    fields = dict(url=a.url, branch=a.branch, token=token)
    if a.platform:
        fields["platform"] = a.platform
    req = AnalysisRequest(**{k: v for k, v in fields.items() if v is not None})

    job = jobs.Job()
    last = {"stage": ""}
    orig = job.update

    def show(stage: str, pct: int, msg: str = "") -> None:
        orig(stage, pct, msg)
        if stage != last["stage"] or msg:
            print(f"[{pct:3d}%] {stage}{': ' + msg if msg else ''}", file=sys.stderr)
            last["stage"] = stage
    job.update = show          # type: ignore[method-assign]
    jobs._run(job, req, token)
    if not job.report:
        print(f"Error: {job.status.error}", file=sys.stderr)
        return 1

    r = job.report
    Path(a.out).write_text(export_html.to_html(r), encoding="utf-8")
    print(f"Informe HTML: {a.out}  (ábralo con doble clic en cualquier navegador)", file=sys.stderr)
    if a.md:
        Path(a.md).write_text(to_markdown(r), encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(r.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
