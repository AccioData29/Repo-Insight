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
    if r.ux:
        u = r.ux
        out += ["## UI/UX", "", f"**Canal:** {u.surface} · **Veredicto:** {u.verdict}", "", u.headline, ""]
        if u.applicable:
            out += ["### Pertinencia", ""] + [f"- {x}" for x in u.pertinence] + ["", "### Dimensiones", ""]
            for d in u.dimensions:
                out.append(f"- **{d.name}** — {d.status} ({d.passed}/{d.total}): " + "; ".join(("✔ " if c.passed else "✘ ") + c.label for c in d.checks))
            out.append("")
            for f in u.findings:
                out += [f"### {f.id} · {f.title}", f"**{SEV[f.severity]}** · confianza {f.confidence}", "", f"**Por qué importa:** {f.why_it_matters}", "",
                        f"**Cómo mejorarlo:** {f.how_to_fix}", "", f"{f.detail}", ""]
                out += [f"- `{e.file}:{e.line}` — {e.snippet}" for e in f.evidence[:4]]
                out.append("")
            out += ["### Límites de esta evaluación", ""] + [f"- {x}" for x in u.limits] + [""]
    if r.authorship and r.authorship.available:
        a = r.authorship
        out += ["## Autoría: IA y equipo", "", f"**{a.headline}**", "",
                f"- {a.commits} commits · {a.first_commit} a {a.last_commit} · {a.lines_analyzed} líneas vigentes · IA declarada: **{a.ai_pct}%** (mínimo)",
                f"- Intervención humana: **{a.intervention_level}** — {a.intervention_text}"] + [f"  - {x}" for x in a.intervention_facts]
        out += ["", "### Herramientas de IA detectadas", ""] + ([f"- {t.tool}: {t.commits} commits, {t.lines_surviving} líneas vigentes ({t.how_detected})" for t in a.tools] or ["- Ninguna declarada."])
        out += ["", "### Por colaborador", "", "| Colaborador | Commits | % del código vigente | Sobrevive | Con IA declarada |", "|---|---|---|---|---|"]
        out += [f"| {c.name} | {c.commits} | {c.codebase_share_pct}% | {c.survival_pct}% | {c.ai_share_pct}% |" for c in a.collaborators]
        out += ["", f"### Bases tecnológicas: {a.foundations_level}", "", a.foundations_text, ""]
        out += [f"- {'✔' if f.passed else '✘'} {f.label}: {f.detail}" for f in a.foundations]
        out += ["", "### Límites", ""] + [f"- {x}" for x in a.limits] + [""]
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
