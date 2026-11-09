import type { Report, UxDimension } from "../../types";
import { ConfidenceBadge, EvidenceLink, SeverityBadge, useAudience } from "../shared";

const VERDICT = {
  bueno: { label: "Bien encaminada", cls: "sev-bg-low" },
  mejorable: { label: "Mejorable", cls: "sev-bg-medium" },
  deficiente: { label: "Con brechas importantes", cls: "sev-bg-high" },
  no_aplica: { label: "No aplica", cls: "badge-cat" },
} as const;
const STATUS = {
  bueno: { label: "Bien resuelto", icon: "✔", cls: "sev-bg-low" },
  aceptable: { label: "Aceptable", icon: "◐", cls: "sev-bg-medium" },
  debil: { label: "Débil", icon: "▲", cls: "sev-bg-high" },
} as const;

function Dimension({ d, technical }: { d: UxDimension; technical: boolean }) {
  const st = STATUS[d.status];
  return (
    <li className="card">
      <div className="row-between">
        <h3>{d.name}</h3>
        <span className={`badge ${st.cls}`}><span aria-hidden>{st.icon}</span> {st.label} · {d.passed}/{d.total}</span>
      </div>
      <p className="help">{d.question}</p>
      <ul className="plain checks">
        {d.checks.map((c) => (
          <li key={c.label}>
            <span className={c.passed ? "sev-low" : "sev-high"} aria-label={c.passed ? "Cumple" : "No cumple"}>{c.passed ? "✔" : "✘"}</span>{" "}
            <strong>{c.label}</strong>
            {technical && <div className="meta">{c.detail}</div>}
          </li>
        ))}
      </ul>
    </li>
  );
}

export default function UxTab({ r }: { r: Report }) {
  const aud = useAudience();
  const u = r.ux;
  if (!u) return null;
  const technical = aud === "tecnica";
  if (!u.applicable) {
    return <div className="card"><h2>UI/UX</h2><p>{u.headline}</p><ul className="plain">{u.limits.map((x) => <li key={x}>{x}</li>)}</ul></div>;
  }
  const v = VERDICT[u.verdict];
  return (
    <div className="stack">
      <section className="card">
        <div className="row-between wrap">
          <div>
            <h2>Experiencia de usuario</h2>
            <p className="meta">{u.surface} · {u.screens} pantalla(s) · {u.ui_files} archivos de interfaz</p>
          </div>
          <span className={`badge ${v.cls}`}>{v.label}</span>
        </div>
        <p className="big">{u.headline}</p>
        {u.screen_names.length > 0 && (
          <>
            <h3>Pantallas detectadas</h3>
            <ul className="chips">{u.screen_names.map((n) => <li key={n} className="chip chip-muted">{n}</li>)}</ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>¿Es pertinente la interfaz para lo que el producto busca?</h2>
        <ul className="plain">{u.pertinence.map((x) => <li key={x}>{x}</li>)}</ul>
        <p className="help">Son inferencias a partir del código y del README, no una medición con personas usuarias.</p>
      </section>

      <section>
        <h2>Por dimensión</h2>
        <ul className="cards dims">{u.dimensions.map((d) => <Dimension key={d.id} d={d} technical={technical} />)}</ul>
      </section>

      <section>
        <h2>Qué mejorar ({u.findings.length})</h2>
        {u.findings.length === 0 && <div className="card"><p>No se detectaron brechas con las verificaciones disponibles.</p></div>}
        <ul className="cards">
          {u.findings.map((f) => (
            <li key={f.id} className={`card sev-border-${f.severity}`}>
              <div className="row-between">
                <span className="mono muted">{f.id}</span>
                <span className="row gap"><SeverityBadge s={f.severity} /><ConfidenceBadge c={f.confidence} /></span>
              </div>
              <h3>{f.title}</h3>
              <h4>¿Cómo afecta a las personas?</h4><p>{f.why_it_matters}</p>
              <h4>¿Cómo se mejora?</h4><p>{f.how_to_fix}</p>
              {technical && (
                <>
                  <p className="meta">{f.detail}</p>
                  {f.evidence.length > 0 && (
                    <details>
                      <summary>Evidencia ({f.evidence.length})</summary>
                      <ul className="evidence">
                        {f.evidence.map((e) => <li key={`${e.file}:${e.line}`}><EvidenceLink meta={r.meta} e={e} /><br /><code>{e.snippet}</code></li>)}
                      </ul>
                    </details>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>Límites de esta evaluación</h3>
        <ul className="plain">{u.limits.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
    </div>
  );
}
