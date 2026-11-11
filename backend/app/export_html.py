"""Informe HTML autocontenido: un solo archivo que se abre en cualquier navegador.

No depende de ningún servicio externo (ni de Claude ni de internet): el informe va incrustado como JSON
y la interfaz (React + Mermaid) viaja dentro del mismo archivo. Plantilla: `npm run build:report`.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Optional

from .models import Report

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    Path(os.environ["REPORT_TEMPLATE"]) if os.getenv("REPORT_TEMPLATE") else None,
    _HERE.parents[2] / "frontend" / "dist-report" / "index.html",
]


class TemplateMissing(RuntimeError):
    pass


def template_path() -> Optional[Path]:
    for c in _CANDIDATES:
        if c and c.is_file():
            return c
    return None


def available() -> bool:
    return template_path() is not None


def to_html(report: Report, template: Optional[Path] = None) -> str:
    path = template or template_path()
    if not path:
        raise TemplateMissing("Falta la plantilla del informe. Genérela con «cd frontend && npm ci && npm run build:report» "
                              "o indique su ruta en REPORT_TEMPLATE.")
    page = path.read_text(encoding="utf-8")
    # JSON seguro dentro de <script>: sin «<» literal (evita cerrar la etiqueta) y ASCII puro.
    data = json.dumps(report.model_dump(mode="json"), ensure_ascii=True).replace("<", "\\u003c")
    marker = '<script type="module"'
    i = page.find(marker)
    if i < 0:
        raise TemplateMissing("La plantilla del informe no tiene el formato esperado; vuelva a generarla.")
    page = page[:i] + f"<script>window.__REPORT__={data}</script>\n    " + page[i:]
    m = report.meta
    title = html.escape(f"Informe · {m.owner}/{m.repo}")
    return re.sub(r"<title>.*?</title>", lambda _: f"<title>{title}</title>", page, count=1, flags=re.S)
