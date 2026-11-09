import type { Report, Severity } from "../../types";
import { SEVERITY_LABEL } from "../../types";
import { SeverityBadge, useAudience } from "../shared";

export default function SummaryTab({ r, go }: { r: Report; go: (tab: string) => void }) {
  const aud = useAudience();
  const k = r.summary.key_numbers;
  const sevs: Severity[] = ["critical", "high", "medium", "low"];
  const counts: Record<Severity, number> = { critical: k.deuda_critica, high: k.deuda_alta, medium: k.deuda_media, low: k.deuda_baja };
  const max = Math.max(1, ...Object.values(counts));
  return (
    <div className="stack">
      <section className="card">
        <div className="row-between">
          <h2>Resumen ejecutivo</h2>
          <SeverityBadge s={r.summary.risk_level} />
        </div>
        <p className="big">{r.summary.headline}</p>
        <h3>¿Qué es este sistema?</h3>
        <p>{r.summary.what_it_does}</p>
        {r.summary.assumptions.length > 0 && (
          <div className="alert alert-info"><strong>Supuestos a confirmar</strong><ul>{r.summary.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>
        )}
      </section>

      <section className="kpis" aria-label="Cifras clave">
        <button className="kpi" onClick={() => go("reglas")}><strong>{k.reglas}</strong><span>reglas de negocio</span></button>
        <button className="kpi" onClick={() => go("flujos")}><strong>{r.flows.length}</strong><span>flujos documentados</span></button>
        <button className="kpi" onClick={() => go("deuda")}><strong>{r.debt.length}</strong><span>hallazgos de deuda técnica</span></button>
        <button className="kpi" onClick={() => go("recomendaciones")}><strong>{k.recomendaciones}</strong><span>recomendaciones</span></button>
        {aud === "tecnica" && <div className="kpi static"><strong>{k.lineas_codigo.toLocaleString("es-CO")}</strong><span>líneas de código</span></div>}
      </section>

      <div className="grid2">
        <section className="card">
          <h3>Deuda técnica por urgencia</h3>
          <ul className="bars">
            {sevs.map((s) => (
              <li key={s}>
                <span className="bar-label">{SEVERITY_LABEL[s]}</span>
                <span className="bar-track"><span className={`bar-val sev-bg-${s}`} style={{ width: `${(counts[s] / max) * 100}%` }} /></span>
                <span className="bar-num">{counts[s]}</span>
              </li>
            ))}
          </ul>
          <p className="help">Crítica: esta semana · Alta: ≤ 30 días · Media: ≤ 90 días · Baja: oportunista.</p>
        </section>
        <section className="card">
          <h3>Principales riesgos</h3>
          <ul className="plain">{r.summary.top_risks.map((t) => <li key={t}>{t}</li>)}</ul>
        </section>
      </div>

      <section className="card">
        <h3>Por dónde empezar</h3>
        <ol className="plain">{r.summary.first_actions.map((a) => <li key={a}>{a}</li>)}</ol>
        <button className="btn btn-secondary" onClick={() => go("deuda")}>Ver toda la deuda técnica →</button>
      </section>
    </div>
  );
}
