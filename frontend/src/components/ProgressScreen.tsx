import { useEffect, useRef, useState } from "react";
import { getStatus } from "../api";
import type { JobStatus } from "../types";

const STAGES = ["Validando origen", "Clonando", "Inventario", "Reglas de negocio", "Flujos", "Arquitectura", "Deuda técnica", "Recomendaciones", "Informe"];

export default function ProgressScreen({ jobId, onDone, onCancel }: { jobId: string; onDone: () => void; onCancel: () => void }) {
  const [s, setS] = useState<JobStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const done = useRef(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const st = await getStatus(jobId);
        if (!alive) return;
        setS(st);
        if (st.status === "done" && !done.current) { done.current = true; onDone(); return; }
        if (st.status === "error") return;
      } catch (e) {
        if (alive) setErr((e as Error).message);
        return;
      }
      if (alive) setTimeout(tick, 1000);
    };
    void tick();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const idx = Math.max(0, STAGES.indexOf(s?.stage ?? ""));
  const failed = s?.status === "error" || !!err;

  return (
    <div className="container narrow">
      <section className="card progress" aria-live="polite">
        <h1>{failed ? "No se pudo completar el análisis" : "Analizando el repositorio…"}</h1>
        {!failed && (
          <>
            <div className="bar" role="progressbar" aria-valuenow={s?.progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
              <div className="bar-fill" style={{ width: `${s?.progress ?? 2}%` }} />
            </div>
            <p className="help">{s?.progress ?? 0}% · {s?.stage ?? "Iniciando"}</p>
            <ol className="stages">
              {STAGES.map((st, i) => (
                <li key={st} className={i < idx ? "done" : i === idx ? "now" : ""}>{i < idx ? "✓" : i === idx ? "●" : "○"} {st}</li>
              ))}
            </ol>
          </>
        )}
        {failed && <div className="alert alert-bad" role="alert"><p>{s?.error ?? err}</p></div>}
        {s && s.log.length > 0 && (
          <details open={failed}>
            <summary>Detalle del proceso</summary>
            <pre className="log">{s.log.slice(-14).join("\n")}</pre>
          </details>
        )}
        <div className="actions">
          <button className="btn btn-secondary" onClick={onCancel}>{failed ? "Volver e intentar de nuevo" : "Cancelar y volver"}</button>
        </div>
      </section>
    </div>
  );
}
