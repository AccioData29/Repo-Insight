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


# ----------------------------- Estado de trabajos -----------------------------

class JobStatus(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "error"]
    stage: str = ""
    progress: int = 0
    log: list[str] = []
    error: Optional[str] = None
