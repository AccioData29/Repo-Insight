export type Severity = "critical" | "high" | "medium" | "low";
export type Confidence = "alta" | "media" | "baja";
export type Platform = "github" | "gitlab" | "azure_devops" | "bitbucket" | "unknown";
export type Privacy = "public" | "private" | "unknown";

export interface PermissionHelp {
  needed: boolean;
  token_kind: string;
  scopes: string[];
  create_url: string;
  steps: string[];
  note: string;
}

export interface SourceValidation {
  valid: boolean;
  platform: Platform;
  platform_label: string;
  analysis_supported: boolean;
  owner: string;
  repo: string;
  normalized_url: string;
  privacy_detected: Privacy;
  accessible: boolean;
  needs_token: boolean;
  default_branch: string | null;
  branches: string[];
  production_branch: string | null;
  production_branch_reason: string;
  permission: PermissionHelp | null;
  messages: string[];
  errors: string[];
}

export interface AppConfig {
  ai_available: boolean;
  platforms: { id: Platform; label: string; analysis_supported: boolean }[];
}

export interface JobStatus {
  id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: number;
  log: string[];
  error: string | null;
}

export interface Evidence { file: string; line: number; snippet: string }

export interface RepoMeta {
  url: string; platform: Platform; platform_label: string; owner: string; repo: string; branch: string;
  branch_assumed: boolean; privacy: Privacy; commit_sha: string; commit_date: string; commit_message: string;
  analyzed_at: string; blob_url_template: string; files_analyzed: number; lines_of_code: number;
}

export interface Rule {
  id: string; category: string; module: string; title: string; description: string;
  condition: string | null; outcome: string | null; confidence: Confidence; evidence: Evidence;
  tags: string[]; ai_enriched: boolean;
}

export interface EntryPoint { id: string; kind: string; method: string | null; route: string | null; name: string; file: string; line: number }
export interface FlowStep { order: number; layer: string; layer_label: string; name: string; file: string; description: string }
export interface Flow {
  id: string; title: string; kind: string; narrative: string; mermaid: string; steps: FlowStep[];
  entry_points: EntryPoint[]; externals: string[]; rule_ids: string[];
}

export interface DebtFinding {
  id: string; category: string; title: string; severity: Severity; urgency: string; why_it_matters: string;
  technical_detail: string; how_to_fix: string; occurrences: number; files_affected: number;
  evidence: Evidence[]; confidence: Confidence;
}

export interface Recommendation {
  id: string; title: string; priority: Severity; effort: "S" | "M" | "L"; current_state: string; proposal: string;
  justification: string; tradeoffs: string; not_recommended_when: string; related_debt: string[];
}

export interface Architecture {
  languages: { language: string; files: number; lines: number; percent: number }[];
  frameworks: string[]; style: string; style_reasons: string[]; data_stores: string[]; messaging: string[];
  auth: string[]; cloud: string[]; containers: string[]; ci_cd: string[]; deployables: string[];
  layers: Record<string, number>; top_level: string[]; domain_entities: string[]; diagram: string;
}

export interface Summary {
  headline: string; what_it_does: string; risk_level: Severity; key_numbers: Record<string, number>;
  top_risks: string[]; first_actions: string[]; assumptions: string[];
}

export interface Report {
  meta: RepoMeta; summary: Summary; architecture: Architecture; rules: Rule[]; entry_points: EntryPoint[];
  flows: Flow[]; debt: DebtFinding[]; recommendations: Recommendation[]; limitations: string[];
}

export type Audience = "negocio" | "tecnica";

export const SEVERITY_LABEL: Record<Severity, string> = { critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" };
export const EFFORT_LABEL: Record<string, string> = { S: "Esfuerzo pequeño", M: "Esfuerzo medio", L: "Esfuerzo grande" };
