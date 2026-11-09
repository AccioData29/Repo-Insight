"""Resumen ejecutivo en lenguaje claro para público mixto."""
from __future__ import annotations

import re
from typing import Optional

from ..models import Architecture, DebtFinding, EntryPoint, Recommendation, Rule, Summary
from .common import Inventory

_RISK_TEXT = {"critical": "Crítico", "high": "Alto", "medium": "Medio", "low": "Bajo"}


def _readme_intro(inv: Inventory) -> Optional[str]:
    for fi in inv.files:
        if fi.rel.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
            text = inv.text(fi)
            paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            for p in paras:
                clean = re.sub(r"!?\[[^\]]*\]\([^)]*\)|<[^>]+>|^#+\s*|^>\s*|`|\*\*", "", p, flags=re.M).strip()
                if len(clean) > 60 and not clean.lower().startswith(("table of contents", "badge")):
                    return re.sub(r"\s+", " ", clean)[:420]
    return None


def build(inv: Inventory, arch: Architecture, rules: list[Rule], entry_points: list[EntryPoint], debt: list[DebtFinding],
          recs: list[Recommendation], loc: int, branch_assumed: bool, branch: str) -> Summary:
    counts = {s: sum(1 for d in debt if d.severity == s) for s in ("critical", "high", "medium", "low")}
    risk = "critical" if counts["critical"] else "high" if counts["high"] else "medium" if counts["medium"] else "low"
    apis = [e for e in entry_points if e.kind == "API"]
    cats: dict[str, int] = {}
    for r in rules:
        cats[r.category] = cats.get(r.category, 0) + 1
    langs = ", ".join(l.language for l in arch.languages[:3]) or "sin lenguajes reconocidos"

    readme = _readme_intro(inv)
    parts = []
    if readme:
        parts.append(f"Según el README del proyecto: {readme}")
    loc_txt = f"{loc:,}".replace(",", ".")
    parts.append(f"El código está escrito principalmente en {langs} (~{loc_txt} líneas de código) y sigue un estilo de «{arch.style.lower()}».")
    if arch.domain_entities:
        parts.append("Conceptos de negocio que aparecen en el modelo: " + ", ".join(arch.domain_entities[:10]) + ".")
    if apis:
        parts.append(f"Expone {len(apis)} operaciones de API y se identificaron {len(rules)} reglas de negocio.")
    else:
        parts.append(f"Se identificaron {len(rules)} reglas de negocio.")

    tops = [d for d in debt if d.severity in ("critical", "high")][:4]
    top_risks = [f"{d.title}: {d.why_it_matters}" for d in tops] or (
        [f"{d.title}: {d.why_it_matters}" for d in debt[:2]] or ["No se detectó deuda técnica relevante con los patrones disponibles."])

    actions = []
    for d in debt[:5]:
        first = d.how_to_fix.split(". ")[0].strip().rstrip(".")
        actions.append(f"[{d.id}] {first}.")
    assumptions = []
    if branch_assumed:
        assumptions.append(f"Se analizó la rama «{branch}» asumiendo que es la de producción; confirme que lo es.")
    if inv.truncated:
        assumptions.append("El repositorio es muy grande: se analizó una parte de los archivos (límite configurable).")
    assumptions.append("Las reglas marcadas con confianza media/baja requieren validación con quien conozca el negocio.")

    headline = (f"Riesgo técnico {_RISK_TEXT[risk].lower()}: {counts['critical']} crítico(s), {counts['high']} alto(s), "
                f"{counts['medium']} medio(s) y {counts['low']} bajo(s). {len(rules)} reglas de negocio identificadas.")
    return Summary(
        headline=headline, what_it_does=" ".join(parts), risk_level=risk,  # type: ignore[arg-type]
        key_numbers={"reglas": len(rules), "flujos": len(entry_points), "deuda_critica": counts["critical"], "deuda_alta": counts["high"],
                     "deuda_media": counts["medium"], "deuda_baja": counts["low"], "lineas_codigo": loc,
                     "recomendaciones": len(recs)},
        top_risks=top_risks, first_actions=actions, assumptions=assumptions)
