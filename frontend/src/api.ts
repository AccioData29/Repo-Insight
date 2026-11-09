import type { AppConfig, JobStatus, Platform, Privacy, Report, SourceValidation } from "./types";

export interface SourcePayload {
  url: string;
  platform?: Platform | null;
  branch?: string | null;
  privacy: Privacy;
  token?: string | null;
  ai_enrichment?: boolean;
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* sin cuerpo */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

const post = (url: string, body: unknown, signal?: AbortSignal) =>
  fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });

export const getConfig = () => fetch("/api/config").then(j<AppConfig>);
export const validateSource = (p: SourcePayload, signal?: AbortSignal) =>
  post("/api/source/validate", { ...p, platform: p.platform ?? null, token: p.token || null }, signal).then(j<SourceValidation>);
export const startAnalysis = (p: SourcePayload) =>
  post("/api/analyses", { ...p, platform: p.platform ?? null, branch: p.branch || null, token: p.token || null }).then(j<JobStatus>);
export const getStatus = (id: string) => fetch(`/api/analyses/${id}`).then(j<JobStatus>);
export const getReport = (id: string) => fetch(`/api/analyses/${id}/report`).then(j<Report>);
export const exportMdUrl = (id: string) => `/api/analyses/${id}/export.md`;
