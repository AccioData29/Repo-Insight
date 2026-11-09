import { useState } from "react";
import { exportMdUrl } from "../api";
import type { Audience, Report } from "../types";
import { AudienceContext } from "./shared";
import ArchitectureTab from "./tabs/ArchitectureTab";
import DebtTab from "./tabs/DebtTab";
import FlowsTab from "./tabs/FlowsTab";
import RecommendationsTab from "./tabs/RecommendationsTab";
import RulesTab from "./tabs/RulesTab";
import SummaryTab from "./tabs/SummaryTab";
import UxTab from "./tabs/UxTab";

const TABS = [
  { id: "resumen", label: "Resumen" },
  { id: "reglas", label: "Reglas de negocio" },
  { id: "flujos", label: "Flujos" },
  { id: "deuda", label: "Deuda técnica" },
  { id: "ux", label: "UI/UX" },
  { id: "arquitectura", label: "Arquitectura" },
  { id: "recomendaciones", label: "Recomendaciones" },
  { id: "limites", label: "Alcance y límites" },
] as const;

export default function ReportScreen({ jobId, report: r, onNew }: { jobId: string; report: Report; onNew: () => void }) {
  const [tab, setTab] = useState<string>("resumen");
  const [aud, setAud] = useState<Audience>("negocio");
  const [rulesKey, setRulesKey] = useState(0);
  const [rulesQuery, setRulesQuery] = useState("");
  const m = r.meta;

  const go = (t: string) => { setTab(t); window.scrollTo({ top: 0 }); };
  const openRules = (q: string) => { setRulesQuery(q); setRulesKey((k) => k + 1); go("reglas"); };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `informe-${m.repo}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <AudienceContext.Provider value={aud}>
      <div className="container">
        <section className="report-head card">
          <div className="row-between wrap">
            <div>
              <h1>{m.owner}/{m.repo}</h1>
              <p className="meta">
                <span className="chip chip-muted">{m.platform_label}</span>{" "}
                <span className="chip chip-muted">{m.privacy === "public" ? "Público" : m.privacy === "private" ? "Privado" : "—"}</span>{" "}
                <span className="chip chip-muted">Rama: {m.branch}</span>{" "}
                <span className="chip chip-muted mono">{m.commit_sha.slice(0, 8)}</span>
              </p>
              <p className="meta">Último commit: {m.commit_date ? new Date(m.commit_date).toLocaleDateString("es-CO") : "—"} · {m.commit_message} · {m.files_analyzed} archivos analizados</p>
            </div>
            <div className="head-actions no-print">
              <div className="seg" role="group" aria-label="Tipo de vista">
                <button className={aud === "negocio" ? "on" : ""} onClick={() => setAud("negocio")}>Vista negocio</button>
                <button className={aud === "tecnica" ? "on" : ""} onClick={() => setAud("tecnica")}>Vista técnica</button>
              </div>
              <div className="row gap">
                {jobId && <a className="btn btn-secondary" href={exportMdUrl(jobId)} download>Markdown</a>}
                {jobId && <button className="btn btn-secondary" onClick={downloadJson}>JSON</button>}
                {jobId && <button className="btn btn-secondary" onClick={() => window.print()}>Imprimir / PDF</button>}
                {jobId && <button className="btn btn-primary" onClick={onNew}>Nuevo análisis</button>}
              </div>
            </div>
          </div>
          {m.branch_assumed && (
            <div className="alert alert-info"><p>Se analizó la rama «{m.branch}» <strong>asumiendo que es la de producción</strong>. Si no lo es, inicie un nuevo análisis indicando la rama correcta.</p></div>
          )}
        </section>

        <div className="tabs no-print" role="tablist" aria-label="Secciones del informe">
          {TABS.filter((t) => t.id !== "ux" || r.ux).map((t) => (
            <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} className={tab === t.id ? "on" : ""}
                    onClick={() => go(t.id)}>
              {t.label}{t.id === "reglas" ? ` (${r.rules.length})` : t.id === "deuda" ? ` (${r.debt.length})` : ""}
            </button>
          ))}
        </div>

        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="panel">
          {tab === "resumen" && <SummaryTab r={r} go={go} />}
          {tab === "reglas" && <RulesTab key={rulesKey} r={r} initialQuery={rulesQuery} />}
          {tab === "flujos" && <FlowsTab r={r} openRules={openRules} />}
          {tab === "deuda" && <DebtTab r={r} />}
          {tab === "ux" && <UxTab r={r} />}
          {tab === "arquitectura" && <ArchitectureTab r={r} />}
          {tab === "recomendaciones" && <RecommendationsTab r={r} />}
          {tab === "limites" && (
            <section className="card">
              <h2>Alcance y límites del análisis</h2>
              <p className="help">Para que nadie tome este informe como más de lo que es:</p>
              <ul className="plain">{r.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
              <p className="meta">Generado el {new Date(m.analyzed_at).toLocaleString("es-CO")}.</p>
            </section>
          )}
        </div>
      </div>
    </AudienceContext.Provider>
  );
}
