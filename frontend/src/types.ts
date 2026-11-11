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

export interface UxCheck {
  dimension: string; label: string; passed: boolean; detail: string; evidence: Evidence[]; severity: Severity | null;
  why_it_matters: string; how_to_fix: string; confidence: Confidence; occurrences: number; files_affected: number;
}
export interface UxDimension { id: string; name: string; question: string; status: "bueno" | "aceptable" | "debil"; checks: UxCheck[]; passed: number; total: number }
export interface UxFinding {
  id: string; dimension: string; title: string; severity: Severity; why_it_matters: string; how_to_fix: string; detail: string;
  occurrences: number; files_affected: number; evidence: Evidence[]; confidence: Confidence;
}
export interface UxReview {
  applicable: boolean; surface: string; verdict: "bueno" | "mejorable" | "deficiente" | "no_aplica"; headline: string; screens: number;
  screen_names: string[]; ui_files: number; dimensions: UxDimension[]; findings: UxFinding[]; pertinence: string[]; limits: string[];
}

export interface AiTool { tool: string; commits: number; lines_surviving: number; how_detected: string; samples: string[] }
export interface Indicator { label: string; observed: boolean; detail: string }
export interface Collaborator {
  name: string; kind: "persona" | "bot" | "ia"; commits: number; ai_declared_commits: number; lines_added: number; lines_surviving: number;
  codebase_share_pct: number; survival_pct: number; ai_share_pct: number; test_share_pct: number; first_commit: string; last_commit: string; top_areas: string[];
}
export interface OriginQuality { origin: string; lines: number; share_pct: number; files_over_600: number; test_share_pct: number; debt_evidence_files: number }
export interface FoundationCheck { label: string; passed: boolean; detail: string; why: string }
export interface AuditCheck { id: string; label: string; status: "cumple" | "parcial" | "no_cumple" | "no_aplica"; severity: "high" | "medium" | "low" | null; detail: string; why: string; how_to_fix: string }
export interface CoauthorAudit { name: string; kind: "persona" | "ia"; commits: number; paired_with: string[]; areas: string[]; first_commit: string; last_commit: string; authored_commits: number; verifiable: boolean; note: string }
export interface AreaOwnership { area: string; lines: number; owner: string; owner_pct: number; ai_pct: number; contributors: number }
export interface PersonActivity { name: string; status: "activa" | "reciente" | "inactiva"; last_commit: string; days_since: number; codebase_share_pct: number }
export interface TimelineSeries { name: string; kind: "persona" | "ia" | "bot"; role: "autor" | "coautor" | "autor y coautor"; commits: number[]; added: number[]; total_commits: number; total_added: number }
export interface TeamTimeline { granularity: "semana" | "mes"; buckets: string[]; total_commits: number[]; total_added: number[]; series: TimelineSeries[]; insights: string[]; note: string }
export interface TeamAudit {
  applicable: boolean; level: "solido" | "mejorable" | "riesgoso" | "no_aplica"; headline: string; people: number; bus_factor: number; top_share_pct: number;
  commits_with_coauthor_pct: number; checks: AuditCheck[]; coauthors: CoauthorAudit[]; areas: AreaOwnership[]; activity: PersonActivity[]; timeline?: TeamTimeline | null; limits: string[];
}

export interface AuthorshipReview {
  available: boolean; reason: string;
  verdict: "ia_mayoritaria" | "mixto" | "humano_con_apoyo_ia" | "senales_sin_atribucion" | "sin_evidencia" | "no_disponible";
  headline: string; commits: number; collaborators_count: number; first_commit: string; last_commit: string; truncated: boolean;
  lines_analyzed: number; lines_ai: number; lines_human: number; lines_bot: number; ai_pct: number; ai_authored_pct: number; ai_coauthored_pct: number;
  ai_added_total: number; ai_survived: number; human_added_total: number; human_survived: number;
  tools: AiTool[]; artifacts: string[]; indicators: Indicator[];
  intervention_level: "alta" | "media" | "baja" | "no_medible"; intervention_text: string; intervention_facts: string[];
  collaborators: Collaborator[]; quality: OriginQuality[];
  foundations_level: "solidas" | "aceptables" | "fragiles"; foundations_text: string; foundations: FoundationCheck[]; team?: TeamAudit | null; limits: string[];
}

export interface Report {
  meta: RepoMeta; summary: Summary; architecture: Architecture; rules: Rule[]; entry_points: EntryPoint[];
  flows: Flow[]; debt: DebtFinding[]; recommendations: Recommendation[]; limitations: string[]; ux?: UxReview | null; authorship?: AuthorshipReview | null;
}

export type Audience = "negocio" | "tecnica";

export const SEVERITY_LABEL: Record<Severity, string> = { critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" };
export const EFFORT_LABEL: Record<string, string> = { S: "Esfuerzo pequeño", M: "Esfuerzo medio", L: "Esfuerzo grande" };
