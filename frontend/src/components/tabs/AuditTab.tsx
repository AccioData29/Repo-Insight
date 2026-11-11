import type { AuditCheck, AuthorshipReview, Report } from "../../types";
import ActivityChart from "../ActivityChart";
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
const LEVEL = { solido: { label: "Controles sólidos", cls: "sev-bg-low" }, mejorable: { label: "Mejorable", cls: "sev-bg-medium" }, riesgoso: { label: "Riesgoso", cls: "sev-bg-high" }, no_aplica: { label: "No aplica", cls: "badge-cat" } } as const;
const STATUS = { cumple: { icon: "✔", cls: "sev-low", text: "Cumple" }, parcial: { icon: "◐", cls: "sev-medium", text: "Parcial" }, no_cumple: { icon: "✘", cls: "sev-high", text: "No cumple" }, no_aplica: { icon: "–", cls: "muted", text: "No aplica" } } as const;
const ACTIVITY = { activa: "Activa", reciente: "Reciente", inactiva: "Inactiva" } as const;

function Check({ c }: { c: AuditCheck }) {
  const st = STATUS[c.status];
  return (
    <li className="check-row">
      <span className={st.cls} aria-label={st.text}>{st.icon}</span>{" "}
      <strong>{c.label}</strong> <span className="meta">· {st.text}</span>
      <div className="meta">{c.detail}</div>
      {c.status !== "cumple" && c.why && <div className="meta"><em>Por qué importa:</em> {c.why}</div>}
      {c.status !== "cumple" && c.how_to_fix && <div className="meta"><em>Qué hacer:</em> {c.how_to_fix}</div>}
    </li>
  );
}


const SECTIONS = [{ id: "ia", label: "Aporte de la IA" }, { id: "tiempo", label: "Actividad en el tiempo" }, { id: "tools", label: "Herramientas" }, { id: "personas", label: "Por colaborador" }, { id: "equipo", label: "Auditoría del equipo" }, { id: "coautores", label: "Coautores" }, { id: "areas", label: "Áreas y actividad" }, { id: "calidad", label: "Calidad por origen" }, { id: "bases", label: "Bases tecnológicas" }, { id: "limites", label: "Límites" }];

function jump(id: string) {
  const el = document.getElementById(`aud-${id}`);
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

export default function AuditTab({ r }: { r: Report }) {
  const aud = useAudience();
  const a = r.authorship;
  if (!a) return null;
  const technical = aud === "tecnica";
  if (!a.available) {
    return <div className="card"><h2>Auditoría IA / equipo</h2><p>{a.reason}</p>
      <p className="help">Para medir la autoría y auditar al equipo el sistema necesita el historial de commits del repositorio.</p></div>;
  }
  const v = VERDICT[a.verdict];
  const botPct = a.lines_analyzed ? Math.round((1000 * a.lines_bot) / a.lines_analyzed) / 10 : 0;
  const f = FOUND[a.foundations_level];
  const t = a.team && a.team.applicable ? a.team : null;
  const lv = t ? LEVEL[t.level] : null;
  const sorted = t ? [...t.checks].sort((x, y) => ["no_cumple", "parcial", "cumple", "no_aplica"].indexOf(x.status) - ["no_cumple", "parcial", "cumple", "no_aplica"].indexOf(y.status)) : [];
  const sections = SECTIONS.filter((s) => (s.id === "tiempo" ? !!t?.timeline : ["equipo", "coautores", "areas"].includes(s.id) ? !!t : true));
  return (
    <div className="stack">
      <nav className="jump no-print" aria-label="Secciones de la auditoría">
        {sections.map((s) => <button key={s.id} onClick={() => jump(s.id)}>{s.label}</button>)}
      </nav>

      <section id="aud-ia" className="card aud-section">
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

      {t?.timeline && (
        <section id="aud-tiempo" className="card aud-section">
          <h2>Actividad en el tiempo</h2>
          <p className="help">Quién aportó y cuándo. Esta gráfica es la evidencia detrás de la auditoría del equipo.</p>
          <ActivityChart tl={t.timeline} />
          {t.timeline.insights.length > 0 && (
            <>
              <h3>Qué se lee en la gráfica</h3>
              <ul className="plain">{t.timeline.insights.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
        </section>
      )}

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

      <section id="aud-tools" className="card aud-section">
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

      <section id="aud-personas" className="aud-section">
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

      {t && lv && (
        <>
      <section id="aud-equipo" className="card aud-section">
        <div className="row-between wrap">
          <div>
            <h2>Auditoría del equipo</h2>
            <p className="meta">Controles de proceso visibles en git · {t.people} persona(s) con commits · {t.coauthors.length} coautor(es) declarado(s)</p>
          </div>
          <span className={`badge ${lv.cls}`}>{lv.label}</span>
        </div>
        <p className="big">{t.headline}</p>
        <div className="kpis">
          <div className="kpi"><strong>{t.bus_factor}</strong>Factor de bus<span className="meta"> personas que concentran más de la mitad del código</span></div>
          <div className="kpi"><strong>{t.top_share_pct}%</strong>Concentración de la persona principal</div>
          <div className="kpi"><strong>{t.commits_with_coauthor_pct}%</strong>Commits con coautor declarado</div>
        </div>
        <p className="help">Es una auditoría de proceso, no una evaluación de desempeño: las líneas de código no miden la calidad ni el esfuerzo de una persona.</p>
      </section>

      <section className="card">
        <h2>Controles de proceso</h2>
        <ul className="plain checks">{sorted.map((c) => <Check key={c.id} c={c} />)}</ul>
      </section>

        </>
      )}

      {t && lv && (
        <>
      <section id="aud-coautores" className="card aud-section">
        <h2>Coautores</h2>
        {t.coauthors.length === 0 ? <p className="help">No hay coautorías declaradas en los mensajes de commit.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Coautor</th><th>Tipo</th><th>Commits</th><th>Verificable</th><th>Qué dice la auditoría</th>{technical && <><th>Con</th><th>Áreas</th><th>Período</th></>}</tr></thead>
            <tbody>{t.coauthors.map((c) => (
              <tr key={`${c.kind}:${c.name}`}>
                <td><strong>{c.name}</strong></td>
                <td>{c.kind === "ia" ? "Herramienta de IA" : "Persona"}</td>
                <td>{n(c.commits)}</td>
                <td>{c.kind === "ia" ? "—" : c.verifiable ? `Sí (${c.authored_commits} commits propios)` : "No"}</td>
                <td>{c.note}</td>
                {technical && <><td>{c.paired_with.join(", ")}</td><td className="mono">{c.areas.join(", ")}</td><td>{c.first_commit} → {c.last_commit}</td></>}
              </tr>
            ))}</tbody>
          </table></div>
        )}
        <p className="help">La coautoría es autodeclarada en el mensaje del commit: git no comprueba que la persona participó.</p>
      </section>

        </>
      )}

      {t && lv && (
        <>
      <section id="aud-areas" className="card aud-section">
        <h2>Quién conoce cada área</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Área</th><th>Líneas vigentes</th><th>Principal responsable</th><th>% del área</th><th>Personas</th><th>Con IA declarada</th></tr></thead>
          <tbody>{t.areas.map((a) => (
            <tr key={a.area}><td className="mono">{a.area}</td><td>{n(a.lines)}</td><td>{a.owner}</td><td>{a.owner_pct}%</td><td>{a.contributors}</td><td>{a.ai_pct}%</td></tr>
          ))}</tbody>
        </table></div>
        <p className="help">Un área con una sola persona responsable es un riesgo de continuidad: si se va, el conocimiento se va con ella.</p>
      </section>

      <section className="card">
        <h2>Actividad reciente</h2>
        <ul className="plain">{t.activity.map((a) => (
          <li key={a.name}><strong>{a.name}</strong>: {ACTIVITY[a.status]} (último commit {a.last_commit}{a.days_since ? `, hace ${a.days_since} días respecto al último cambio del repositorio` : ""}) · {a.codebase_share_pct}% del código vigente</li>
        ))}</ul>
      </section>

        </>
      )}

      <section id="aud-calidad" className="card aud-section">
        <h2>Calidad según el origen del código</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Origen (por archivo)</th><th>Líneas</th><th>% del código</th><th>Archivos &gt; 600 líneas</th><th>% en pruebas</th><th>Archivos con deuda</th></tr></thead>
          <tbody>{a.quality.map((q) => (
            <tr key={q.origin}><td><strong>{q.origin}</strong></td><td>{n(q.lines)}</td><td>{q.share_pct}%</td><td>{q.files_over_600}</td><td>{q.test_share_pct}%</td><td>{q.debt_evidence_files}</td></tr>
          ))}</tbody>
        </table></div>
        <p className="help">Un archivo se asigna a «IA declarada» si la mitad o más de sus líneas vigentes vienen de commits con IA. «Archivos con deuda» cuenta los de la muestra de evidencia de deuda técnica.</p>
      </section>

      <section id="aud-bases" className="card aud-section">
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

      <section id="aud-limites" className="card aud-section">
        <h3>Límites de esta evaluación</h3>
        <ul className="plain">{[...a.limits, ...(t?.limits ?? [])].map((x) => <li key={x}>{x}</li>)}</ul>
      </section>

    </div>
  );
}
