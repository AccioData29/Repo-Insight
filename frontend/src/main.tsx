import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ReportScreen from "./components/ReportScreen";
import type { Report } from "./types";
import "./styles.css";

// Modo «informe publicado»: el HTML trae el informe incrustado y no necesita servidor.
const embedded = (window as unknown as { __REPORT__?: Report }).__REPORT__;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {embedded ? (
      <main className="container"><ReportScreen jobId="" report={embedded} onNew={() => window.print()} /></main>
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
