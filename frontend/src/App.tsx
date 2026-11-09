import { useEffect, useState } from "react";
import { getReport, getStatus } from "./api";
import ProgressScreen from "./components/ProgressScreen";
import ReportScreen from "./components/ReportScreen";
import SourceScreen from "./components/SourceScreen";
import type { Report } from "./types";

type Screen = { name: "source" } | { name: "running"; jobId: string } | { name: "report"; jobId: string; report: Report };

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: "source" });

  // si se recarga la página, intenta recuperar el informe de la sesión (los trabajos viven en memoria en el servidor)
  useEffect(() => {
    const id = sessionStorage.getItem("ri.job");
    if (!id) return;
    getStatus(id)
      .then(async (s) => {
        if (s.status === "done") setScreen({ name: "report", jobId: id, report: await getReport(id) });
        else if (s.status === "running" || s.status === "queued") setScreen({ name: "running", jobId: id });
      })
      .catch(() => sessionStorage.removeItem("ri.job"));
  }, []);

  const start = (jobId: string) => { sessionStorage.setItem("ri.job", jobId); setScreen({ name: "running", jobId }); };
  const reset = () => { sessionStorage.removeItem("ri.job"); setScreen({ name: "source" }); };

  return (
    <>
      <a href="#main" className="skip">Saltar al contenido</a>
      <header className="topbar">
        <button className="brand" onClick={reset} aria-label="Volver al inicio">
          <span className="brand-mark" aria-hidden>◇</span> Repo Insight
        </button>
        <span className="tagline">Entienda un repositorio sin leer todo el código</span>
      </header>
      <main id="main">
        {screen.name === "source" && <SourceScreen onStarted={start} />}
        {screen.name === "running" && (
          <ProgressScreen
            jobId={screen.jobId}
            onDone={async () => setScreen({ name: "report", jobId: screen.jobId, report: await getReport(screen.jobId) })}
            onCancel={reset}
          />
        )}
        {screen.name === "report" && <ReportScreen jobId={screen.jobId} report={screen.report} onNew={reset} />}
      </main>
    </>
  );
}
