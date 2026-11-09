import type { Report } from "../../types";
import Mermaid from "../Mermaid";
import { Chips, useAudience } from "../shared";

export default function ArchitectureTab({ r }: { r: Report }) {
  const a = r.architecture;
  const aud = useAudience();
  const maxLayer = Math.max(1, ...Object.values(a.layers));
  return (
    <div className="stack">
      <section className="card">
        <h2>Arquitectura</h2>
        <p className="big">{a.style}</p>
        {a.style_reasons.length > 0 && <ul className="plain">{a.style_reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
        <h3>Mapa del sistema</h3>
        <Mermaid code={a.diagram} title="Mapa de contexto del sistema" />
      </section>

      <div className="grid2">
        <section className="card">
          <h3>Lenguajes</h3>
          <ul className="bars">
            {a.languages.map((l) => (
              <li key={l.language}><span className="bar-label">{l.language}</span>
                <span className="bar-track"><span className="bar-val bar-neutral" style={{ width: `${l.percent}%` }} /></span>
                <span className="bar-num">{l.percent}%</span></li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Componentes por rol</h3>
          <ul className="bars">
            {Object.entries(a.layers).map(([k, v]) => (
              <li key={k}><span className="bar-label wide">{k}</span>
                <span className="bar-track"><span className="bar-val bar-neutral" style={{ width: `${(v / maxLayer) * 100}%` }} /></span>
                <span className="bar-num">{v}</span></li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card">
        <h3>Tecnologías detectadas</h3>
        <dl className="defs">
          <dt>Frameworks y librerías</dt><dd><Chips items={a.frameworks} /></dd>
          <dt>Bases de datos</dt><dd><Chips items={a.data_stores} /></dd>
          <dt>Mensajería / colas</dt><dd><Chips items={a.messaging} /></dd>
          <dt>Autenticación</dt><dd><Chips items={a.auth} /></dd>
          <dt>Nube</dt><dd><Chips items={a.cloud} /></dd>
          <dt>Contenedores / infraestructura</dt><dd><Chips items={a.containers} /></dd>
          <dt>CI/CD</dt><dd><Chips items={a.ci_cd} /></dd>
          {a.deployables.length > 0 && <><dt>Componentes desplegables</dt><dd><Chips items={a.deployables} /></dd></>}
        </dl>
      </section>

      {a.domain_entities.length > 0 && (
        <section className="card"><h3>Conceptos de negocio en el modelo</h3><Chips items={a.domain_entities} /></section>
      )}

      {aud === "tecnica" && (
        <section className="card"><h3>Estructura de primer nivel</h3><pre className="code">{a.top_level.join("\n")}</pre></section>
      )}
    </div>
  );
}
