import { useMemo, useState } from "react";
import type { Report } from "../../types";
import { ConfidenceBadge, EvidenceLink, useAudience } from "../shared";

const TECH_CAT = "Error técnico controlado";
const PAGE = 40;

export default function RulesTab({ r, initialQuery = "" }: { r: Report; initialQuery?: string }) {
  const aud = useAudience();
  const [q, setQ] = useState(initialQuery);
  const [cat, setCat] = useState("");
  const [mod, setMod] = useState("");
  const [conf, setConf] = useState("");
  const [shown, setShown] = useState(PAGE);

  const cats = useMemo(() => {
    const m = new Map<string, number>();
    r.rules.forEach((x) => m.set(x.category, (m.get(x.category) ?? 0) + 1));
    return [...m.entries()];
  }, [r.rules]);
  const modules = useMemo(() => [...new Set(r.rules.map((x) => x.module))].sort((a, b) => a.localeCompare(b)), [r.rules]);

  const list = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return r.rules.filter((x) => {
      if (!cat && aud === "negocio" && x.category === TECH_CAT) return false;   // para negocio, los errores técnicos no son reglas
      if (cat && x.category !== cat) return false;
      if (mod && x.module !== mod) return false;
      if (conf && x.confidence !== conf) return false;
      if (ql && !(`${x.id} ${x.title} ${x.description} ${x.module} ${x.condition ?? ""} ${x.evidence.file}`.toLowerCase().includes(ql))) return false;
      return true;
    });
  }, [r.rules, q, cat, mod, conf, aud]);

  const reset = () => { setQ(""); setCat(""); setMod(""); setConf(""); setShown(PAGE); };

  return (
    <div className="stack">
      <section className="card">
        <h2>Reglas de negocio</h2>
        <p className="help">
          Extraídas del código fuente de la rama analizada. Cada regla indica su <strong>nivel de confianza</strong>: las de confianza media/baja son inferencias y conviene validarlas con quien conozca el negocio.
          {aud === "negocio" && " Los mensajes de error puramente técnicos están ocultos; cámbiese a «Vista técnica» o elija esa categoría para verlos."}
        </p>
        <div className="filters">
          <div className="field grow">
            <label htmlFor="rq">Buscar</label>
            <input id="rq" type="search" value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} placeholder="Ej.: monto, cliente bloqueado, rol…" />
          </div>
          <div className="field">
            <label htmlFor="rc">Tipo de regla</label>
            <select id="rc" value={cat} onChange={(e) => { setCat(e.target.value); setShown(PAGE); }}>
              <option value="">Todos</option>
              {cats.map(([c, n]) => <option key={c} value={c}>{c} ({n})</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rm">Módulo / área</label>
            <select id="rm" value={mod} onChange={(e) => { setMod(e.target.value); setShown(PAGE); }}>
              <option value="">Todos</option>
              {modules.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rf">Confianza</label>
            <select id="rf" value={conf} onChange={(e) => { setConf(e.target.value); setShown(PAGE); }}>
              <option value="">Todas</option><option value="alta">Alta</option><option value="media">Media</option><option value="baja">Baja</option>
            </select>
          </div>
        </div>
        <p className="help" aria-live="polite">{list.length} regla(s) {list.length !== r.rules.length && <button className="link-btn" onClick={reset}>Quitar filtros</button>}</p>
      </section>

      <ul className="cards">
        {list.slice(0, shown).map((x) => (
          <li key={x.id} className="card rule">
            <div className="row-between">
              <span className="mono muted">{x.id}</span>
              <span className="row gap"><span className="badge badge-cat">{x.category}</span><ConfidenceBadge c={x.confidence} /></span>
            </div>
            <h3>{x.title}</h3>
            <p>{x.description}</p>
            <p className="meta">Área: <strong>{x.module}</strong>{x.ai_enriched && " · redactada con IA"}</p>
            {aud === "tecnica" && (
              <dl className="tech">
                {x.condition && <><dt>Condición en el código</dt><dd><code>{x.condition}</code></dd></>}
                {x.outcome && <><dt>Resultado</dt><dd><code>{x.outcome}</code></dd></>}
                <dt>Evidencia</dt><dd><EvidenceLink meta={r.meta} e={x.evidence} /><br /><code>{x.evidence.snippet}</code></dd>
              </dl>
            )}
          </li>
        ))}
      </ul>
      {list.length > shown && <button className="btn btn-secondary" onClick={() => setShown(shown + PAGE)}>Mostrar más ({list.length - shown} restantes)</button>}
      {list.length === 0 && <div className="card"><p>No hay reglas con esos filtros.</p></div>}
    </div>
  );
}
