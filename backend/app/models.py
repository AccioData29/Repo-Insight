"""Modelos de la API y del informe (contrato entre backend y frontend)."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, SecretStr


class Platform(str, Enum):
    github = "github"
    gitlab = "gitlab"
    azure_devops = "azure_devops"
    bitbucket = "bitbucket"
    unknown = "unknown"


class Privacy(str, Enum):
    public = "public"
    private = "private"
    unknown = "unknown"


# ----------------------------- Origen del repositorio -----------------------------

class SourceRequest(BaseModel):
    url: str
    platform: Optional[Platform] = None          # si el usuario la elige a mano
    branch: Optional[str] = None                 # rama de producción (opcional)
    privacy: Privacy = Privacy.unknown           # lo que declara el usuario
    token: Optional[SecretStr] = None            # solo lectura; nunca se persiste ni se registra


class PermissionHelp(BaseModel):
    needed: bool
    token_kind: str = ""
    scopes: list[str] = []
    create_url: str = ""
    steps: list[str] = []
    note: str = ""


class SourceValidation(BaseModel):
    valid: bool
    platform: Platform = Platform.unknown
    platform_label: str = ""
    analysis_supported: bool = False
    owner: str = ""
    repo: str = ""
    normalized_url: str = ""
    privacy_detected: Privacy = Privacy.unknown
    accessible: bool = False
    needs_token: bool = False
    default_branch: Optional[str] = None
    branches: list[str] = []
    production_branch: Optional[str] = None
    production_branch_reason: str = ""
    permission: Optional[PermissionHelp] = None
    messages: list[str] = []
    errors: list[str] = []


class AnalysisRequest(SourceRequest):
    ai_enrichment: bool = False


# ----------------------------- Informe -----------------------------

Severity = Literal["critical", "high", "medium", "low"]
Confidence = Literal["alta", "media", "baja"]


class Evidence(BaseModel):
    file: str
    line: int
    snippet: str


class RepoMeta(BaseModel):
    url: str
    platform: Platform
    platform_label: str
    owner: str
    repo: str
    branch: str
    branch_assumed: bool
    privacy: Privacy
    commit_sha: str = ""
    commit_date: str = ""
    commit_message: str = ""
    analyzed_at: str
    blob_url_template: str = ""     # con {sha} {path} {line}
    files_analyzed: int = 0
    lines_of_code: int = 0


class Rule(BaseModel):
    id: str
    category: str
    module: str
    title: str
    description: str                 # lenguaje de negocio
    condition: Optional[str] = None  # expresión original (vista técnica)
    outcome: Optional[str] = None
    confidence: Confidence
    evidence: Evidence
    tags: list[str] = []
    ai_enriched: bool = False


class EntryPoint(BaseModel):
    id: str
    kind: str                        # API, Proceso programado, Consumidor de cola, Pantalla...
    method: Optional[str] = None
    route: Optional[str] = None
    name: str
    file: str
    line: int


class FlowStep(BaseModel):
    order: int
    layer: str
    layer_label: str
    name: str
    file: str
    description: str


class Flow(BaseModel):
    id: str
    title: str
    kind: str
    narrative: str
    mermaid: str
    steps: list[FlowStep]
    entry_points: list[EntryPoint]
    externals: list[str]
    rule_ids: list[str]


class DebtFinding(BaseModel):
    id: str
    category: str
    title: str
    severity: Severity
    urgency: str
    why_it_matters: str              # lenguaje de negocio
    technical_detail: str
    how_to_fix: str
    occurrences: int
    files_affected: int
    evidence: list[Evidence]
    confidence: Confidence = "alta"


class Recommendation(BaseModel):
    id: str
    title: str
    priority: Severity
    effort: Literal["S", "M", "L"]
    current_state: str
    proposal: str
    justification: str
    tradeoffs: str
    not_recommended_when: str
    related_debt: list[str] = []


class LangStat(BaseModel):
    language: str
    files: int
    lines: int
    percent: float


class Architecture(BaseModel):
    languages: list[LangStat]
    frameworks: list[str]
    style: str
    style_reasons: list[str]
    data_stores: list[str]
    messaging: list[str]
    auth: list[str]
    cloud: list[str]
    containers: list[str]
    ci_cd: list[str]
    deployables: list[str]
    layers: dict[str, int]
    top_level: list[str]
    domain_entities: list[str]
    diagram: str


class Summary(BaseModel):
    headline: str
    what_it_does: str
    risk_level: Severity
    key_numbers: dict[str, int]
    top_risks: list[str]
    first_actions: list[str]
    assumptions: list[str]


class UxCheck(BaseModel):
    dimension: str
    label: str
    passed: bool
    detail: str
    evidence: list[Evidence] = []
    severity: Optional[Severity] = None
    why_it_matters: str = ""
    how_to_fix: str = ""
    confidence: Confidence = "media"
    occurrences: int = 0
    files_affected: int = 0


class UxDimension(BaseModel):
    id: str
    name: str
    question: str
    status: Literal["bueno", "aceptable", "debil"]
    checks: list[UxCheck]
    passed: int
    total: int


class UxFinding(BaseModel):
    id: str
    dimension: str
    title: str
    severity: Severity
    why_it_matters: str
    how_to_fix: str
    detail: str
    occurrences: int
    files_affected: int
    evidence: list[Evidence]
    confidence: Confidence = "media"


class UxReview(BaseModel):
    applicable: bool
    surface: str
    verdict: Literal["bueno", "mejorable", "deficiente", "no_aplica"]
    headline: str
    screens: int = 0
    screen_names: list[str] = []
    ui_files: int = 0
    dimensions: list[UxDimension] = []
    findings: list[UxFinding] = []
    pertinence: list[str] = []
    limits: list[str] = []


class AiTool(BaseModel):
    tool: str
    commits: int
    lines_surviving: int = 0
    how_detected: str
    samples: list[str] = []


class Indicator(BaseModel):
    label: str
    observed: bool
    detail: str


class Collaborator(BaseModel):
    name: str
    kind: Literal["persona", "bot", "ia"]
    commits: int
    ai_declared_commits: int
    lines_added: int
    lines_surviving: int
    codebase_share_pct: float
    survival_pct: float
    ai_share_pct: float                 # % de SUS líneas vigentes que vienen de commits con IA declarada
    test_share_pct: float               # % de sus líneas vigentes que están en pruebas
    first_commit: str = ""
    last_commit: str = ""
    top_areas: list[str] = []


class OriginQuality(BaseModel):
    origin: str                         # "IA declarada" | "Humano / sin declarar"
    lines: int
    share_pct: float
    files_over_600: int
    test_share_pct: float
    debt_evidence_files: int


class FoundationCheck(BaseModel):
    label: str
    passed: bool
    detail: str
    why: str = ""


class AuditCheck(BaseModel):
    id: str
    label: str
    status: Literal["cumple", "parcial", "no_cumple", "no_aplica"]
    severity: Optional[Literal["high", "medium", "low"]] = None
    detail: str
    why: str = ""
    how_to_fix: str = ""


class CoauthorAudit(BaseModel):
    name: str
    kind: Literal["persona", "ia"]
    commits: int
    paired_with: list[str] = []
    areas: list[str] = []
    first_commit: str = ""
    last_commit: str = ""
    authored_commits: int = 0
    verifiable: bool = False
    note: str = ""


class AreaOwnership(BaseModel):
    area: str
    lines: int
    owner: str
    owner_pct: float
    ai_pct: float
    contributors: int


class PersonActivity(BaseModel):
    name: str
    status: Literal["activa", "reciente", "inactiva"]
    last_commit: str
    days_since: int
    codebase_share_pct: float


class TimelineSeries(BaseModel):
    name: str
    kind: Literal["persona", "ia", "bot"]
    role: Literal["autor", "coautor", "autor y coautor"]
    commits: list[int]
    added: list[int]
    total_commits: int
    total_added: int


class TeamTimeline(BaseModel):
    granularity: Literal["semana", "mes"]
    buckets: list[str]                      # fecha de inicio de cada periodo (YYYY-MM-DD)
    total_commits: list[int]
    total_added: list[int]
    series: list[TimelineSeries]
    insights: list[str] = []
    note: str = ""


class TeamAudit(BaseModel):
    applicable: bool
    level: Literal["solido", "mejorable", "riesgoso", "no_aplica"] = "no_aplica"
    headline: str = ""
    people: int = 0
    bus_factor: int = 0
    top_share_pct: float = 0
    commits_with_coauthor_pct: float = 0
    checks: list[AuditCheck] = []
    coauthors: list[CoauthorAudit] = []
    areas: list[AreaOwnership] = []
    activity: list[PersonActivity] = []
    timeline: Optional[TeamTimeline] = None
    limits: list[str] = []


class AuthorshipReview(BaseModel):
    available: bool
    reason: str = ""
    verdict: Literal["ia_mayoritaria", "mixto", "humano_con_apoyo_ia", "senales_sin_atribucion", "sin_evidencia", "no_disponible"] = "no_disponible"
    headline: str = ""
    commits: int = 0
    collaborators_count: int = 0
    first_commit: str = ""
    last_commit: str = ""
    truncated: bool = False
    lines_analyzed: int = 0
    lines_ai: int = 0
    lines_human: int = 0
    lines_bot: int = 0
    ai_pct: float = 0
    ai_authored_pct: float = 0          # IA como autora directa (bot/agente)
    ai_coauthored_pct: float = 0        # IA declarada como coautora de un commit de una persona
    ai_added_total: int = 0
    ai_survived: int = 0
    human_added_total: int = 0
    human_survived: int = 0
    tools: list[AiTool] = []
    artifacts: list[str] = []
    indicators: list[Indicator] = []
    intervention_level: Literal["alta", "media", "baja", "no_medible"] = "no_medible"
    intervention_text: str = ""
    intervention_facts: list[str] = []
    collaborators: list[Collaborator] = []
    quality: list[OriginQuality] = []
    foundations_level: Literal["solidas", "aceptables", "fragiles"] = "aceptables"
    foundations_text: str = ""
    foundations: list[FoundationCheck] = []
    team: Optional[TeamAudit] = None
    limits: list[str] = []


class Report(BaseModel):
    meta: RepoMeta
    summary: Summary
    architecture: Architecture
    rules: list[Rule]
    entry_points: list[EntryPoint]
    flows: list[Flow]
    debt: list[DebtFinding]
    recommendations: list[Recommendation]
    limitations: list[str]
    ux: Optional[UxReview] = None
    authorship: Optional[AuthorshipReview] = None


# ----------------------------- Estado de trabajos -----------------------------

class JobStatus(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "error"]
    stage: str = ""
    progress: int = 0
    log: list[str] = []
    error: Optional[str] = None
