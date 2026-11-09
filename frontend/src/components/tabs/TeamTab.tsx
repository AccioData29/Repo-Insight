import type { AuditCheck, Report } from "../../types";
import { useAudience } from "../shared";

const LEVEL = { solido: { label: "Controles sólidos", cls: "sev-bg-low" }, mejorable: { label: "Mejorable", cls: "sev-bg-medium" }, riesgoso: { label: "Riesgoso", cls: "sev-bg-high" }, no_aplica: { label: "No aplica", cls: "badge-cat" } } as const;
const STATUS = { cumple: { icon: "✔", cls: "sev-low", text: "Cumple" }, parcial: { icon: "◐", cls: "sev-medium", text: "Parcial" }, no_cumple: { icon: "✘", cls: "sev-high", text: "No cumple" }, no_aplica: { icon: "–", cls: "muted", text: "No aplica" } } as const;
const ACTIVITY = { activa: "Activa", reciente: "Reciente", inactiva: "Inactiva" } as const;
const n = (x: number) => x.toLocaleString("es-CO");

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

export default function TeamTab({ r }: { r: Report }) {
  const aud = useAudience();
  const t = r.authorship?.team;
  if (!t || !t.applicable) return null;
  const technical = aud === "tecnica";
  const lv = LEVEL[t.level];
  const sorted = [...t.checks].sort((a, b) => ["no_cumple", "parcial", "cumple", "no_aplica"].indexOf(a.status) - ["no_cumple", "parcial", "cumple", "no_aplica"].indexOf(b.status));
  return (
    <div className="stack">
      <section className="card">
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

      <section className="card">
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

      <section className="card">
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

      <section className="card">
        <h3>Límites de esta auditoría</h3>
        <ul className="plain">{t.limits.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
    </div>
  );
}
