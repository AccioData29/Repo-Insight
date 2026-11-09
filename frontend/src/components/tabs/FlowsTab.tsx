import { useMemo, useState } from "react";
import type { Report } from "../../types";
import Mermaid from "../Mermaid";
import { Chips, EvidenceLink, useAudience } from "../shared";

export default function FlowsTab({ r, openRules }: { r: Report; openRules: (q: string) => void }) {
  const aud = useAudience();
  const [sel, setSel] = useState(r.flows[0]?.id ?? "");
  const flow = r.flows.find((f) => f.id === sel);
  const rulesById = useMemo(() => new Map(r.rules.map((x) => [x.id, x])), [r.rules]);

  if (!r.flows.length) {
    return <div className="card"><h2>Flujos</h2><p>No se detectaron puntos de entrada con una cadena de componentes reconocible. Revise la lista de puntos de entrada en la vista técnica.</p></div>;
  }
  const flowRules = (flow?.rule_ids ?? []).map((id) => rulesById.get(id)).filter(Boolean).filter((x) => aud === "tecnica" || x!.category !== "Error técnico controlado");

  return (
    <div className="split">
      <nav className="side card" aria-label="Flujos">
        <h2>Flujos</h2>
        <ul className="navlist">
          {r.flows.map((f) => (
            <li key={f.id}>
              <button className={f.id === sel ? "on" : ""} aria-current={f.id === sel} onClick={() => setSel(f.id)}>
                <strong>{f.title}</strong>
                <small>{f.entry_points.length} entrada(s) · {f.steps.length} componentes</small>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {flow && (
        <div className="stack">
          <section className="card">
            <h2>{flow.title}</h2>
            <p className="big">{flow.narrative}</p>
            <h3>Recorrido</h3>
            <Mermaid code={flow.mermaid} title={`Diagrama del flujo ${flow.title}`} />
            <p className="legend">
              <span className="lg lg-controller">Entrada</span><span className="lg lg-service">Lógica de negocio</span><span className="lg lg-repository">Datos</span>
              <span className="lg lg-integration">Integración</span><span className="lg lg-ext">Sistema externo (línea punteada)</span>
            </p>
            {flow.externals.length > 0 && <><h3>Sistemas con los que interactúa</h3><Chips items={flow.externals} /></>}
          </section>

          <section className="card">
            <h3>Pasos del flujo</h3>
            <ol className="timeline">
              {flow.steps.map((s) => (
                <li key={s.order}>
                  <span className="badge badge-cat">{s.layer_label}</span> <strong>{s.name}</strong>
                  {aud === "tecnica" && <div className="mono muted">{s.file}</div>}
                </li>
              ))}
            </ol>
          </section>

          <section className="card">
            <div className="row-between"><h3>Reglas que intervienen ({flowRules.length})</h3>
              <button className="link-btn" onClick={() => openRules("")}>Ver todas las reglas →</button></div>
            {flowRules.length === 0 ? <p className="help">No se asociaron reglas a los archivos de este flujo.</p> : (
              <ul className="plain">
                {flowRules.slice(0, 12).map((x) => <li key={x!.id}><span className="mono muted">{x!.id}</span> {x!.description}</li>)}
              </ul>
            )}
            {flowRules.length > 12 && <p className="help">…y {flowRules.length - 12} más en la pestaña de reglas.</p>}
          </section>

          {aud === "tecnica" && (
            <section className="card">
              <h3>Puntos de entrada de este flujo</h3>
              <div className="table-wrap"><table>
                <thead><tr><th>Tipo</th><th>Método</th><th>Ruta</th><th>Manejador</th><th>Archivo</th></tr></thead>
                <tbody>{flow.entry_points.map((e) => (
                  <tr key={e.id}><td>{e.kind}</td><td>{e.method ?? "—"}</td><td className="mono">{e.route ?? "—"}</td><td className="mono">{e.name}</td>
                    <td><EvidenceLink meta={r.meta} e={{ file: e.file, line: e.line, snippet: "" }} /></td></tr>
                ))}</tbody>
              </table></div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
