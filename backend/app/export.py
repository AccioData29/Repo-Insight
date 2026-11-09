"""Exportación del informe a Markdown (para compartir/versionar)."""
from __future__ import annotations

from .models import Report

SEV = {"critical": "🔴 Crítica", "high": "🟠 Alta", "medium": "🟡 Media", "low": "🟢 Baja"}


def to_markdown(r: Report) -> str:
    m, s = r.meta, r.summary
    out = [f"# Informe de {m.owner}/{m.repo}", "",
           f"- **Plataforma:** {m.platform_label} · **Privacidad:** {m.privacy.value} · **Rama:** `{m.branch}`"
           + (" (asumida como producción)" if m.branch_assumed else ""),
           f"- **Commit:** `{m.commit_sha[:10]}` · {m.commit_date} · {m.commit_message}",
           f"- **Analizado:** {m.analyzed_at} · {m.files_analyzed} archivos · ~{m.lines_of_code} líneas de código", "",
           "## Resumen", "", s.headline, "", s.what_it_does, "", "### Principales riesgos", ""]
    out += [f"- {x}" for x in s.top_risks]
    out += ["", "### Primeras acciones", ""] + [f"- {x}" for x in s.first_actions]
    out += ["", "## Deuda técnica (por urgencia)", ""]
    for d in r.debt:
        out += [f"### {d.id} · {d.title}", f"**{SEV[d.severity]}** — {d.urgency}", "", f"**Por qué importa:** {d.why_it_matters}", "",
                f"**Detalle técnico:** {d.technical_detail}", "", f"**Cómo corregirlo:** {d.how_to_fix}", "",
                f"Ocurrencias: {d.occurrences} en {d.files_affected} archivo(s). Confianza: {d.confidence}.", ""]
        for e in d.evidence[:5]:
            out.append(f"- `{e.file}:{e.line}` — {e.snippet}")
        out.append("")
    out += ["## Reglas de negocio", ""]
    cat = None
    for rule in r.rules:
        if rule.category != cat:
            cat = rule.category
            out += [f"### {cat}", ""]
        out.append(f"- **{rule.id}** ({rule.confidence}) {rule.description} — `{rule.evidence.file}:{rule.evidence.line}`")
    out += ["", "## Flujos", ""]
    for f in r.flows:
        out += [f"### {f.id} · {f.title}", "", f.narrative, "", "```mermaid", f.mermaid, "```", ""]
    out += ["## Arquitectura", "", f"**Estilo:** {r.architecture.style}", "",
            f"**Lenguajes:** " + ", ".join(f"{l.language} {l.percent}%" for l in r.architecture.languages),
            f"**Frameworks:** " + ", ".join(r.architecture.frameworks),
            f"**Datos:** " + ", ".join(r.architecture.data_stores), "", "```mermaid", r.architecture.diagram, "```", "",
            "## Recomendaciones", ""]
    for rec in r.recommendations:
        out += [f"### {rec.id} · {rec.title} ({SEV[rec.priority]}, esfuerzo {rec.effort})", "",
                f"**Situación actual:** {rec.current_state}", "", f"**Propuesta:** {rec.proposal}", "",
                f"**Justificación técnica:** {rec.justification}", "", f"**Costos / trade-offs:** {rec.tradeoffs}", "",
                f"**Cuándo NO aplicarla:** {rec.not_recommended_when}", ""]
    out += ["## Limitaciones", ""] + [f"- {x}" for x in r.limitations]
    return "\n".join(out)
