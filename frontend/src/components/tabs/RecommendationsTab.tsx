import type { Report } from "../../types";
import { EFFORT_LABEL } from "../../types";
import { SeverityBadge, useAudience } from "../shared";

export default function RecommendationsTab({ r }: { r: Report }) {
  const aud = useAudience();
  return (
    <div className="stack">
      <section className="card">
        <h2>Recomendaciones de arquitectura y tecnología</h2>
        <p className="help">
          Cada recomendación parte de un hallazgo concreto del código y explica su justificación, su costo y <strong>cuándo no aplicarla</strong>.
          No se propone cambiar de tecnología sin una causa medible. Lo que no puede verificarse desde el código (volumen real, presupuesto, equipo, contratos) debe contrastarse con la organización.
        </p>
      </section>
      <ul className="cards">
        {r.recommendations.map((x) => (
          <li key={x.id} className="card">
            <div className="row-between">
              <span className="mono muted">{x.id}</span>
              <span className="row gap"><SeverityBadge s={x.priority} /><span className="badge badge-cat">{EFFORT_LABEL[x.effort]}</span></span>
            </div>
            <h3>{x.title}</h3>
            <h4>Situación actual</h4><p>{x.current_state}</p>
            <h4>Propuesta</h4><p>{x.proposal}</p>
            <h4>{aud === "tecnica" ? "Justificación técnica" : "¿Por qué esta propuesta?"}</h4><p>{x.justification}</p>
            <h4>Costos y compromisos</h4><p>{x.tradeoffs}</p>
            {x.not_recommended_when && <><h4>Cuándo NO aplicarla</h4><p>{x.not_recommended_when}</p></>}
            {x.related_debt.length > 0 && <p className="meta">Resuelve: {x.related_debt.join(", ")}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
