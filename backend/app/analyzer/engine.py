"""Orquestador del análisis."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..models import Platform, Privacy, Report, RepoMeta
from . import architecture, debt, enrich, flows, recommendations, rules as rules_mod, summary, ux, authorship
from .common import Inventory

Progress = Callable[[str, int, str], None]


def analyze_directory(root: Path, meta: dict, progress: Optional[Progress] = None, ai: bool = False) -> Report:
    """Analiza un directorio ya clonado (solo lectura). `meta` trae los datos del origen."""
    p = progress or (lambda stage, pct, msg: None)

    p("Inventario", 30, "Recorriendo archivos…")
    inv = Inventory(root)
    p("Inventario", 36, f"{len(inv.files)} archivos")

    p("Reglas de negocio", 42, "Extrayendo reglas de negocio…")
    rule_list = rules_mod.extract_rules(inv)
    p("Reglas de negocio", 55, f"{len(rule_list)} reglas")

    p("Flujos", 58, "Detectando puntos de entrada y dependencias…")
    entry_points = flows.find_entry_points(inv)
    graph = flows.build_graph(inv)
    flow_list = flows.build_flows(inv, entry_points, rule_list, graph)
    p("Flujos", 70, f"{len(entry_points)} puntos de entrada, {len(flow_list)} flujos")

    p("Arquitectura", 72, "Identificando arquitectura y tecnologías…")
    arch, loc = architecture.detect(inv, graph[0], len(rule_list))

    p("Deuda técnica", 78, "Evaluando deuda técnica…")
    debt_list = debt.run_all(inv)
    p("Deuda técnica", 88, f"{len(debt_list)} hallazgos")

    p("UI/UX", 89, "Evaluando la interfaz de usuario…")
    ux_review = ux.build(inv, entry_points)

    p("Autoría", 90, "Midiendo autoría (IA y personas) con el historial de git…")
    authorship_review = authorship.build(root, inv, debt_list, arch)
    p("Autoría", 91, authorship_review.headline[:120])

    p("Recomendaciones", 92, "Evaluando alternativas de arquitectura…")
    recs = recommendations.build(inv, arch, debt_list, rule_list)

    if ai and enrich.available():
        p("Redacción con IA", 93, "Reescribiendo reglas en lenguaje de negocio…")
        n = enrich.enrich_rules(rule_list, lambda m: p("Redacción con IA", 93, m))
        p("Redacción con IA", 95, f"{n} reglas reescritas")

    p("Informe", 97, "Armando el informe…")
    sm = summary.build(inv, arch, rule_list, entry_points, debt_list, recs, loc, bool(meta.get("branch_assumed")), meta["branch"])
    report = Report(
        meta=RepoMeta(
            url=meta["url"], platform=meta.get("platform", Platform.unknown), platform_label=meta.get("platform_label", ""),
            owner=meta.get("owner", ""), repo=meta.get("repo", ""), branch=meta["branch"], branch_assumed=bool(meta.get("branch_assumed")),
            privacy=meta.get("privacy", Privacy.unknown), commit_sha=meta.get("sha", ""), commit_date=meta.get("date", ""),
            commit_message=meta.get("message", ""), analyzed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            blob_url_template=meta.get("blob_url_template", ""), files_analyzed=len(inv.files), lines_of_code=loc),
        summary=sm, architecture=arch, rules=rule_list, entry_points=entry_points, flows=flow_list, debt=debt_list,
        recommendations=recs, limitations=recommendations.LIMITATIONS, ux=ux_review, authorship=authorship_review)
    return report
