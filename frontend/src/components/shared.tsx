import { createContext, useContext } from "react";
import type { Audience, Confidence, Evidence, RepoMeta, Severity } from "../types";
import { SEVERITY_LABEL } from "../types";

export const AudienceContext = createContext<Audience>("negocio");
export const useAudience = () => useContext(AudienceContext);

export function SeverityBadge({ s }: { s: Severity }) {
  const icon = { critical: "▲▲", high: "▲", medium: "■", low: "●" }[s];
  return <span className={`badge sev-${s}`}><span aria-hidden>{icon}</span> {SEVERITY_LABEL[s]}</span>;
}

export function ConfidenceBadge({ c }: { c: Confidence }) {
  const text = { alta: "Confianza alta", media: "Confianza media: validar con negocio", baja: "Confianza baja: inferida" }[c];
  return <span className={`badge conf-${c}`} title={text}>{c === "alta" ? "●●●" : c === "media" ? "●●○" : "●○○"} {text.split(":")[0]}</span>;
}

export function blobUrl(meta: RepoMeta, e: Evidence): string | null {
  if (!meta.blob_url_template || !e.file.includes(".") || e.line < 1) return null;
  return meta.blob_url_template
    .replace("{sha}", meta.commit_sha)
    .replace("{path}", e.file.split("/").map(encodeURIComponent).join("/"))
    .replace("{line}", String(e.line));
}

export function EvidenceLink({ meta, e }: { meta: RepoMeta; e: Evidence }) {
  const url = blobUrl(meta, e);
  const label = e.line > 0 ? `${e.file}:${e.line}` : e.file;
  return url ? <a href={url} target="_blank" rel="noopener noreferrer" className="mono link">{label} ↗</a> : <span className="mono">{label}</span>;
}

export function Chips({ items, empty = "Ninguno detectado" }: { items: string[]; empty?: string }) {
  if (!items.length) return <span className="help">{empty}</span>;
  return <ul className="chips">{items.map((i) => <li key={i} className="chip chip-muted">{i}</li>)}</ul>;
}
