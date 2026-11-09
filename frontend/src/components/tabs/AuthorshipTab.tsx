import type { AuthorshipReview, Report } from "../../types";
import { useAudience } from "../shared";

const VERDICT: Record<AuthorshipReview["verdict"], { label: string; cls: string }> = {
  ia_mayoritaria: { label: "Predominantemente generado con IA", cls: "sev-bg-high" },
  mixto: { label: "Desarrollo mixto: personas + IA", cls: "sev-bg-medium" },
  humano_con_apoyo_ia: { label: "Mayormente humano, con apoyo de IA", cls: "sev-bg-low" },
  senales_sin_atribucion: { label: "Señales de IA sin atribución", cls: "sev-bg-medium" },
  sin_evidencia: { label: "Sin evidencia de IA", cls: "sev-bg-low" },
  no_disponible: { label: "No disponible", cls: "badge-cat" },
};
const INTERVENTION = { alta: "Alta", media: "Media", baja: "Baja", no_medible: "No medible" } as const;
const FOUND = { solidas: { label: "Sólidas", cls: "sev-bg-low" }, aceptables: { label: "Aceptables", cls: "sev-bg-medium" }, fragiles: { label: "Frágiles", cls: "sev-bg-high" } } as const;
const KIND = { persona: "Persona", bot: "Automatización", ia: "Agente de IA" } as const;
const n = (x: number) => x.toLocaleString("es-CO");

function Bar({ ai, bot }: { ai: number; bot: number }) {
  const human = Math.max(0, 100 - ai - bot);
  return (
    <div className="stackbar" role="img" aria-label={`IA declarada ${ai}%, personas o sin declarar ${human}%, automatizaciones ${bot}%`}>
      <span className="seg-ai" style={{ width: `${ai}%` }} />
      <span className="seg-human" style={{ width: `${human}%` }} />
      {bot > 0 && <span className="seg-bot" style={{ width: `${bot}%` }} />}
    </div>
  );
}

export default function AuthorshipTab({ r }: { r: Report }) {
  const aud = useAudience();
  const a = r.authorship;
  if (!a) return null;
  const technical = aud === "tecnica";
  if (!a.available) {
    return <div className="card"><h2>Autoría IA / equipo</h2><p>{a.reason}</p>
      <p className="help">Para medir la autoría el sistema necesita el historial de commits del repositorio.</p></div>;
  }
  const v = VERDICT[a.verdict];
  const botPct = a.lines_analyzed ? Math.round((1000 * a.lines_bot) / a.lines_analyzed) / 10 : 0;
  const f = FOUND[a.foundations_level];
  return (
    <div className="stack">
      <section className="card">
        <div className="row-between wrap">
          <div>
            <h2>¿Cuánto aportó la IA?</h2>
            <p className="meta">{n(a.commits)} commits · {a.first_commit} a {a.last_commit} · {a.collaborators_count} persona(s) · {n(a.lines_analyzed)} líneas vigentes analizadas</p>
          </div>
          <span className={`badge ${v.cls}`}>{v.label}</span>
        </div>
        <p className="big">{a.headline}</p>
        <Bar ai={a.ai_pct} bot={botPct} />
        <ul className="legend2">
          <li><span className="dot seg-ai" /> IA declarada: <strong>{a.ai_pct}%</strong> de las líneas vigentes</li>
          <li><span className="dot seg-human" /> Personas / sin declarar: <strong>{Math.round((100 - a.ai_pct - botPct) * 10) / 10}%</strong></li>
          {botPct > 0 && <li><span className="dot seg-bot" /> Automatizaciones: <strong>{botPct}%</strong></li>}
        </ul>
        <p className="help">«Vigente» es el código que hoy está en la rama de producción, no todo lo que alguna vez se escribió. El porcentaje es un <strong>mínimo</strong>: solo cuenta la IA que dejó huella.</p>
      </section>

      <div className="grid2">
        <section className="card">
          <h3>Código escrito vs. código que se quedó</h3>
          <dl className="defs">
            <dt>Escrito con IA declarada</dt><dd>{n(a.ai_added_total)} líneas</dd>
            <dt>De eso, sigue vigente</dt><dd><strong>{a.ai_added_total ? Math.round((1000 * a.ai_survived) / a.ai_added_total) / 10 : 0}%</strong> ({n(a.ai_survived)})</dd>
            <dt>Escrito por personas</dt><dd>{n(a.human_added_total)} líneas</dd>
            <dt>De eso, sigue vigente</dt><dd><strong>{a.human_added_total ? Math.round((1000 * a.human_survived) / a.human_added_total) / 10 : 0}%</strong> ({n(a.human_survived)})</dd>
          </dl>
          <p className="help">Si mucho código de IA no sobrevive, fue regenerado o reescrito. Si casi todo sobrevive, se aceptó tal cual.</p>
        </section>
        <section className="card">
          <h3>Intervención humana: <span className="inline">{INTERVENTION[a.intervention_level]}</span></h3>
          <p>{a.intervention_text}</p>
          <ul className="plain">{a.intervention_facts.map((x) => <li key={x}>{x}</li>)}</ul>
        </section>
      </div>

      <section className="card">
        <h3>Herramientas de IA detectadas</h3>
        {a.tools.length === 0 ? <p className="help">No se encontraron commits con IA declarada.</p> : (
          <ul className="plain">
            {a.tools.map((t) => (
              <li key={t.tool}><strong>{t.tool}</strong>: {n(t.commits)} commits, {n(t.lines_surviving)} líneas vigentes. <span className="meta">{t.how_detected}.</span>
                {technical && t.samples.map((s) => <div key={s} className="mono muted">{s}</div>)}</li>
            ))}
          </ul>
        )}
        {a.artifacts.length > 0 && (
          <>
            <h4>Archivos de configuración de asistentes</h4>
            <ul className="plain">{a.artifacts.map((x) => <li key={x} className="mono">{x}</li>)}</ul>
          </>
        )}
      </section>

      <section>
        <h2>Por colaborador</h2>
        <div className="card table-wrap">
          <table>
            <thead><tr><th>Colaborador</th><th>Commits</th><th>% del código vigente</th><th>Sobrevive de lo escrito</th><th>Con IA declarada</th>{technical && <><th>En pruebas</th><th>Áreas</th><th>Período</th></>}</tr></thead>
            <tbody>
              {a.collaborators.map((c) => (
                <tr key={c.name}>
                  <td><strong>{c.name}</strong><div className="meta">{KIND[c.kind]}</div></td>
                  <td>{n(c.commits)}</td>
                  <td>{c.codebase_share_pct}%</td>
                  <td>{c.survival_pct}%</td>
                  <td>{c.ai_share_pct}%<div className="meta">{c.ai_declared_commits} commits</div></td>
                  {technical && <><td>{c.test_share_pct}%</td><td className="mono">{c.top_areas.join(", ")}</td><td>{c.first_commit} → {c.last_commit}</td></>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="help">Los nombres salen del historial de git y pueden ser alias o cuentas compartidas. «Con IA declarada» es la parte de lo vigente de esa persona que viene de commits donde declaró coautoría de IA.</p>
      </section>

      <section className="card">
        <h2>Calidad según el origen del código</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Origen (por archivo)</th><th>Líneas</th><th>% del código</th><th>Archivos &gt; 600 líneas</th><th>% en pruebas</th><th>Archivos con deuda</th></tr></thead>
          <tbody>{a.quality.map((q) => (
            <tr key={q.origin}><td><strong>{q.origin}</strong></td><td>{n(q.lines)}</td><td>{q.share_pct}%</td><td>{q.files_over_600}</td><td>{q.test_share_pct}%</td><td>{q.debt_evidence_files}</td></tr>
          ))}</tbody>
        </table></div>
        <p className="help">Un archivo se asigna a «IA declarada» si la mitad o más de sus líneas vigentes vienen de commits con IA. «Archivos con deuda» cuenta los de la muestra de evidencia de deuda técnica.</p>
      </section>

      <section className="card">
        <div className="row-between wrap"><h2>¿Tiene buenas bases tecnológicas?</h2><span className={`badge ${f.cls}`}>{f.label}</span></div>
        <p className="big">{a.foundations_text}</p>
        <ul className="plain checks">
          {a.foundations.map((c) => (
            <li key={c.label}>
              <span className={c.passed ? "sev-low" : "sev-high"} aria-label={c.passed ? "Cumple" : "No cumple"}>{c.passed ? "✔" : "✘"}</span> <strong>{c.label}</strong>
              <div className="meta">{c.detail}{!c.passed && c.why ? ` ${c.why}` : ""}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>Señales de estilo (no cuentan en el porcentaje)</h3>
        <ul className="plain checks">
          {a.indicators.map((i) => (
            <li key={i.label}><span aria-label={i.observed ? "Observada" : "No observada"}>{i.observed ? "●" : "○"}</span> <strong>{i.label}</strong>
              <div className="meta">{i.detail}</div></li>
          ))}
        </ul>
        <p className="help">Son compatibles con IA y con equipos humanos ordenados. No prueban quién escribió el código.</p>
      </section>

      <section className="card">
        <h3>Límites de esta evaluación</h3>
        <ul className="plain">{a.limits.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
    </div>
  );
}
