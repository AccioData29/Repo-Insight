import { useState } from "react";
import type { Report, Severity } from "../../types";
import { SEVERITY_LABEL } from "../../types";
import { ConfidenceBadge, EvidenceLink, SeverityBadge, useAudience } from "../shared";

const ORDER: Severity[] = ["critical", "high", "medium", "low"];

export default function DebtTab({ r }: { r: Report }) {
  const aud = useAudience();
  const [filter, setFilter] = useState<Severity | "">("");
  const counts = Object.fromEntries(ORDER.map((s) => [s, r.debt.filter((d) => d.severity === s).length])) as Record<Severity, number>;
  const list = r.debt.filter((d) => !filter || d.severity === filter);

  return (
    <div className="stack">
      <section className="card">
        <h2>Deuda técnica</h2>
        <p className="help">Ordenada por urgencia. La urgencia combina el impacto potencial en el negocio con la facilidad de explotación o de que ocurra una falla.</p>
        <div className="seg" role="group" aria-label="Filtrar por urgencia">
          <button className={!filter ? "on" : ""} onClick={() => setFilter("")}>Todas ({r.debt.length})</button>
          {ORDER.map((s) => (
            <button key={s} className={filter === s ? "on" : ""} disabled={!counts[s]} onClick={() => setFilter(s)}>{SEVERITY_LABEL[s]} ({counts[s]})</button>
          ))}
        </div>
      </section>

      {list.length === 0 && <div className="card"><p>No se detectó deuda técnica con los patrones disponibles. Eso no garantiza su ausencia: vea «Alcance y límites».</p></div>}

      <ul className="cards">
        {list.map((d) => (
          <li key={d.id} className={`card debt sev-border-${d.severity}`}>
            <div className="row-between">
              <span className="mono muted">{d.id} · {d.category}</span>
              <span className="row gap"><SeverityBadge s={d.severity} /><ConfidenceBadge c={d.confidence} /></span>
            </div>
            <h3>{d.title}</h3>
            <p className="urgency"><strong>Urgencia:</strong> {d.urgency}</p>
            <h4>¿Por qué importa?</h4>
            <p>{d.why_it_matters}</p>
            <h4>¿Cómo se corrige?</h4>
            <p>{d.how_to_fix}</p>
            {aud === "tecnica" && (
              <>
                <h4>Detalle técnico</h4>
                <p className="prewrap">{d.technical_detail}</p>
                <p className="meta">{d.occurrences} ocurrencia(s) en {d.files_affected} archivo(s).</p>
                {d.evidence.length > 0 && (
                  <details open={d.severity === "critical"}>
                    <summary>Evidencia ({d.evidence.length} de muestra)</summary>
                    <ul className="evidence">
                      {d.evidence.map((e) => (
                        <li key={`${e.file}:${e.line}`}><EvidenceLink meta={r.meta} e={e} /><br /><code>{e.snippet}</code></li>
                      ))}
                    </ul>
                    <p className="help">Los valores de credenciales se ocultan siempre en este informe.</p>
                  </details>
                )}
              </>
            )}
            {aud === "negocio" && <p className="meta">{d.occurrences} ocurrencia(s). Cambie a «Vista técnica» para ver la evidencia exacta.</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
