"""Autoría del código: cuánto aportó la IA, cuánto sobrevive en la versión vigente y qué intervención humana hubo.

Qué mide (con evidencia verificable en git):
  * Atribución EXPLÍCITA de IA: trailers «Co-Authored-By: Claude/Copilot/…», autores-bot/agente, «Generated with …».
  * Código VIGENTE: con `git blame` se sabe qué commit escribió cada línea que hoy está en producción.
  * Intervención humana: commits sin IA sobre archivos que nacieron de la IA, líneas vigentes de personas en esos archivos, revisiones.
  * Por colaborador: commits, líneas escritas, líneas que sobreviven, % de su aporte asistido por IA.

Qué NO puede hacer: detectar IA que no dejó huella (código pegado desde un chat). Por eso el porcentaje es un MÍNIMO.
No se usan «detectores de texto de IA»: no son confiables. Los indicadores de estilo se muestran aparte y no entran en el porcentaje.
No se exponen correos electrónicos.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Optional

from ..models import (AiTool, Architecture, AuthorshipReview, Collaborator, DebtFinding, FoundationCheck, Indicator,
                      OriginQuality)
from .common import TEST_RE, FileInfo, Inventory

MAX_COMMITS = int(os.getenv("AUTHORSHIP_MAX_COMMITS", "6000"))
MAX_BLAME_FILES = int(os.getenv("AUTHORSHIP_MAX_BLAME_FILES", "1500"))
BLAME_BUDGET_S = int(os.getenv("AUTHORSHIP_BLAME_BUDGET_S", "150"))

AI_TRAILERS: list[tuple[str, re.Pattern]] = [
    ("Claude (Anthropic)", re.compile(r"co-authored-by:\s*claude|noreply@anthropic\.com|generated with \[?claude code|claude\.ai/code/session", re.I)),
    ("GitHub Copilot", re.compile(r"co-authored-by:\s*(?:github\s*)?copilot|copilot-swe-agent|copilot@github\.com|generated (?:by|with) (?:github )?copilot", re.I)),
    ("Cursor", re.compile(r"co-authored-by:\s*cursor|cursoragent@|(?:made|generated) (?:with|by) cursor", re.I)),
    ("Aider", re.compile(r"^aider:|\(aider\)|co-authored-by:\s*aider", re.I | re.M)),
    ("OpenAI Codex / ChatGPT", re.compile(r"co-authored-by:\s*(?:codex|chatgpt|openai)|chatgpt-codex-connector|generated (?:by|with) (?:chatgpt|codex)", re.I)),
    ("Gemini (Google)", re.compile(r"co-authored-by:\s*gemini|generated with gemini|gemini-code-assist", re.I)),
    ("Devin", re.compile(r"devin-ai-integration|co-authored-by:\s*devin", re.I)),
    ("Windsurf / Cline / otros", re.compile(r"co-authored-by:\s*(?:windsurf|cline|codeium|amazon q)|generated with (?:windsurf|cline)", re.I)),
    ("IA (sin especificar)", re.compile(r"co-authored-by:[^\n]*\b(?:ai|llm)\b|generated (?:by|with) ai\b|ai-generated|assisted-by:", re.I)),
]
AI_IDENTITY = re.compile(r"(?i)copilot-swe-agent|devin-ai|\(aider\)|^claude\b|claude\[bot\]|anthropic|cursor\s?agent|codex|openhands|sweep-ai|\bai[-\s]?agent\b")
BOT_IDENTITY = re.compile(r"(?i)\[bot\]|dependabot|renovate|github-actions|greenkeeper|snyk-bot|bot@|-bot$|^bot[-\s]")
ARTIFACTS = [
    (re.compile(r"(^|/)CLAUDE\.md$|(^|/)\.claude/"), "Claude Code"),
    (re.compile(r"(^|/)AGENTS\.md$"), "Agentes de IA (AGENTS.md)"),
    (re.compile(r"(^|/)GEMINI\.md$|(^|/)\.gemini/"), "Gemini CLI"),
    (re.compile(r"(^|/)\.cursorrules$|(^|/)\.cursor/"), "Cursor"),
    (re.compile(r"(^|/)\.github/copilot-instructions\.md$|(^|/)\.github/instructions/"), "GitHub Copilot"),
    (re.compile(r"(^|/)\.aider[^/]*$"), "Aider"),
    (re.compile(r"(^|/)\.windsurfrules$|(^|/)\.windsurf/|(^|/)\.clinerules|(^|/)\.continue/|(^|/)\.codex/"), "Windsurf / Cline / Continue / Codex"),
    (re.compile(r"(^|/)\.mcp\.json$"), "Servidores MCP"),
    (re.compile(r"(?i)(^|/)prompts?/"), "Carpeta de prompts"),
]
CODE_EXT = {".css", ".scss", ".html", ".md"}

CLS_AI_AUTHOR, CLS_AI_CO, CLS_BOT, CLS_HUMAN = "ia_autor", "ia_coautor", "bot", "humano"


@dataclass
class Commit:
    sha: str
    parents: int
    author: str
    date: str
    subject: str
    body: str
    cls: str
    tool: str = ""
    added: int = 0
    deleted: int = 0
    files: dict[str, int] = field(default_factory=dict)       # ruta -> líneas agregadas


def _git(root: Path, *args: str, timeout: int = 120) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"}
    cmd = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.quotepath=false", "-C", str(root), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""


def _classify(author: str, email: str, committer: str, committer_email: str, body: str, subject: str) -> tuple[str, str]:
    ident = f"{author} <{email}>"
    text = f"{ident}\n{committer} <{committer_email}>\n{subject}\n{body}"
    tool = ""
    for name, rx in AI_TRAILERS:
        if rx.search(text):
            tool = name
            break
    if AI_IDENTITY.search(ident):
        return CLS_AI_AUTHOR, tool or "IA (agente)"
    if tool:
        return CLS_AI_CO, tool
    if BOT_IDENTITY.search(ident):
        return CLS_BOT, ""
    return CLS_HUMAN, ""


def _parse_log(root: Path) -> tuple[list[Commit], bool]:
    fmt = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%s%x1f%B%x1f"
    out = _git(root, "log", "--use-mailmap", "--no-renames", "--numstat", f"-n{MAX_COMMITS + 1}", f"--format={fmt}", timeout=180)
    commits: list[Commit] = []
    for rec in out.split("\x1e")[1:]:
        parts = rec.split("\x1f")
        if len(parts) < 10:
            continue
        sha, parents, an, ae, date, cn, ce, subject, body, rest = parts[:10]
        cls, tool = _classify(an, ae, cn, ce, body, subject)
        c = Commit(sha=sha, parents=len(parents.split()), author=an.strip() or ae.split("@")[0], date=date, subject=subject.strip(), body=body, cls=cls, tool=tool)
        for line in rest.strip().splitlines():
            m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line)
            if not m:
                continue
            a = 0 if m.group(1) == "-" else int(m.group(1))
            d = 0 if m.group(2) == "-" else int(m.group(2))
            c.added += a
            c.deleted += d
            c.files[m.group(3)] = c.files.get(m.group(3), 0) + a
        commits.append(c)
    truncated = len(commits) > MAX_COMMITS
    return commits[:MAX_COMMITS], truncated


_BLAME_HEAD = re.compile(r"^([0-9a-f]{40}) \d+ \d+ (\d+)$")


def _blame(root: Path, rel: str) -> dict[str, int]:
    out = _git(root, "blame", "-w", "--porcelain", "--", rel, timeout=60)
    counts: dict[str, int] = defaultdict(int)
    for line in out.splitlines():
        m = _BLAME_HEAD.match(line)
        if m:
            counts[m.group(1)] += int(m.group(2))
    return counts


def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _day(iso: str) -> str:
    return iso[:10]


def _identity_key(c: Commit) -> str:
    return c.author.strip().lower()


def _build_indicators(commits: list[Commit], inv: Inventory, total_added: int) -> list[Indicator]:
    out: list[Indicator] = []
    n = len(commits)
    big = [c for c in commits if c.added >= 800 or len(c.files) >= 25]
    share = _pct(len(big), n)
    out.append(Indicator(label="Commits muy grandes (800+ líneas o 25+ archivos)", observed=n >= 5 and share >= 15,
                         detail=f"{len(big)} de {n} commits ({share}%). Los asistentes de IA suelen entregar cambios grandes de una vez."))
    structured = [c for c in commits if len([l for l in c.body.strip().splitlines() if l.strip()]) >= 4 and re.search(r"(?m)^\s*[-*•]\s", c.body)]
    share = _pct(len(structured), n)
    out.append(Indicator(label="Mensajes de commit largos y con viñetas", observed=n >= 5 and share >= 40,
                         detail=f"{len(structured)} de {n} commits ({share}%). Es un patrón común en mensajes redactados por IA, pero también en equipos ordenados."))
    first = commits[-1] if commits else None
    first_share = _pct(first.added, total_added) if first else 0
    out.append(Indicator(label="Carga inicial masiva", observed=bool(first and first.added >= 2000 and first_share >= 35),
                         detail=f"El primer commit aporta {first.added if first else 0} líneas ({first_share}% de todo lo escrito en el historial)."))
    proc = [f.rel for f in inv.files if re.search(r"(?i)(^|/)(evidencias|specs?|spec-kit|agents?|prompts?)/|(^|/)(HU|US|AJ)-?\d+", f.rel)]
    out.append(Indicator(label="Documentación de proceso (especificaciones, historias, evidencias, prompts)", observed=len(proc) >= 5,
                         detail=f"{len(proc)} archivos de ese tipo. Suele acompañar el desarrollo guiado por especificaciones con IA, pero también la gestión formal."))
    return out


def _foundations(inv: Inventory, debt: list[DebtFinding], arch: Architecture) -> list[FoundationCheck]:
    checks: list[FoundationCheck] = []
    code = [f for f in inv.files if f.is_code and not f.is_generated]
    tests = [f for f in code if f.is_test]
    prod = [f for f in code if not f.is_test]
    ratio = len(tests) / len(prod) if prod else 0
    checks.append(FoundationCheck(label="Pruebas automáticas", passed=len(tests) >= 3 and ratio >= 0.12,
                                  detail=f"{len(tests)} archivos de prueba para {len(prod)} de código ({int(ratio * 100)}%).",
                                  why="Es la red de seguridad que permite cambiar código generado sin romperlo; sin pruebas, nadie puede afirmar que funciona."))
    ci = [f.rel for f in inv.files if re.search(r"(?i)(^|/)\.github/workflows/|azure-pipelines|\.gitlab-ci\.yml|Jenkinsfile|bitbucket-pipelines|\.circleci/", f.rel)]
    checks.append(FoundationCheck(label="Integración continua", passed=bool(ci), detail=f"{len(ci)} archivo(s) de pipeline." if ci else "No hay pipeline que ejecute pruebas y controles en cada cambio.",
                                  why="Sin ella, ninguna revisión es automática y los errores llegan a producción."))
    lint = [f.rel for f in inv.files if re.search(r"(?i)(^|/)(\.eslintrc[^/]*|eslint\.config\.[a-z]+|\.prettierrc[^/]*|prettier\.config\.[a-z]+|ruff\.toml|\.flake8|\.pylintrc|\.editorconfig|sonar-project\.properties|biome\.jsonc?|checkstyle[^/]*\.xml|\.ktlint|detekt[^/]*\.ya?ml|stylecop[^/]*\.json)$", f.rel)]
    checks.append(FoundationCheck(label="Reglas automáticas de estilo y calidad (lint/formato)", passed=bool(lint), detail=", ".join(lint[:3]) if lint else "No se detectan linters ni formateadores.",
                                  why="Mantienen un estilo único cuando muchas manos (o muchos prompts) escriben el mismo código."))
    strict = False
    typed_detail = ""
    for f in inv.files:
        if re.search(r"(^|/)tsconfig[^/]*\.json$", f.rel):
            t = inv.text(f)
            if re.search(r'"strict"\s*:\s*true', t):
                strict, typed_detail = True, f"TypeScript en modo estricto ({f.rel})."
                break
            if re.search(r'"extends"\s*:\s*"(@react-native/typescript-config|@tsconfig/strictest|@tsconfig/strict|expo/tsconfig\.base|@tsconfig/react-native)', t):
                strict, typed_detail = True, f"TypeScript con una base estricta heredada ({f.rel})."
                break
    if not strict:
        size_by_lang: Counter[str] = Counter()
        for f in prod:
            size_by_lang[f.lang or "?"] += f.size
        dominant = size_by_lang.most_common(1)[0][0] if size_by_lang else ""
        if dominant in {"C#", "Java", "Kotlin", "Go", "Rust", "Swift"}:
            strict, typed_detail = True, f"{dominant} es de tipado estático."
        elif dominant == "Python" and any(re.search(r"(?i)\[tool\.(mypy|pyright)|^\[mypy", inv.text(f)[:6000]) or f.name in ("mypy.ini", "pyrightconfig.json")
                                          for f in inv.files if f.name in ("pyproject.toml", "setup.cfg", "mypy.ini", "pyrightconfig.json")):
            strict, typed_detail = True, "Verificación de tipos en Python."
        elif dominant in ("TypeScript", "JavaScript"):
            typed_detail = "El código principal es TypeScript/JavaScript sin modo estricto verificable." if dominant == "TypeScript" else "El código principal es JavaScript sin tipos."
    checks.append(FoundationCheck(label="Tipado verificado por el compilador", passed=strict, detail=typed_detail or "No se detecta tipado estricto.",
                                  why="Detecta en compilación los errores de integración que el código generado suele introducir."))
    arch_txt = (arch.style or "").lower()
    layered = bool(re.search(r"capas|hexagonal|limpia|clean|modular|microserv|mvc|vertical|onion|ddd", arch_txt)) and "sin " not in arch_txt[:6]
    checks.append(FoundationCheck(label="Estructura por capas o módulos", passed=layered, detail=arch.style or "No se identificó un estilo.",
                                  why="Sin una estructura clara, el código crece por acumulación y cada cambio toca todo."))
    manifests = [f for f in inv.files if f.name in ("package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "go.mod", "Cargo.toml") or f.ext == ".csproj"]
    locks = [f for f in inv.files if f.name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "packages.lock.json", "go.sum", "Cargo.lock", "gradle.lockfile")]
    checks.append(FoundationCheck(label="Dependencias reproducibles", passed=bool(locks) or not manifests,
                                  detail=f"{len(locks)} archivo(s) de bloqueo de versiones." if locks else "Hay manifiestos pero no archivos de bloqueo.",
                                  why="Sin versiones fijas, el mismo código puede comportarse distinto mañana."))
    readme = next((f for f in inv.files if f.rel.lower() in ("readme.md", "readme.rst", "readme")), None)
    readme_lines = len(inv.lines(readme)) if readme else 0
    docs = any(f.rel.lower().startswith(("docs/", "doc/")) for f in inv.files)
    checks.append(FoundationCheck(label="Documentación", passed=readme_lines >= 15, detail=f"README de {readme_lines} líneas" + (" y carpeta docs." if docs else "."),
                                  why="Quien recibe el proyecto necesita entender qué hace, cómo se ejecuta y por qué se decidió así."))
    sec = [d for d in debt if d.severity in ("critical", "high") and d.category == "Seguridad"]
    checks.append(FoundationCheck(label="Sin riesgos de seguridad críticos o altos", passed=not sec,
                                  detail="; ".join(d.title for d in sec[:3]) if sec else "No se detectan secretos expuestos ni inyección SQL con prioridad alta.",
                                  why="Los asistentes de IA reproducen malas prácticas conocidas (claves en el código, consultas concatenadas)."))
    silent = [d for d in debt if "silenciados" in d.title and d.severity in ("medium", "high", "critical")]
    checks.append(FoundationCheck(label="Manejo de errores explícito", passed=not silent,
                                  detail=silent[0].title if silent else "No se detectan errores silenciados de forma significativa.",
                                  why="El código generado tiende a «tragarse» errores para que parezca que funciona."))
    giant = [d for d in debt if "gigantes" in d.title and d.severity in ("medium", "high", "critical")]
    checks.append(FoundationCheck(label="Archivos de tamaño manejable", passed=not giant,
                                  detail=giant[0].title if giant else "No hay archivos desproporcionados.",
                                  why="Los archivos enormes concentran lógica mezclada y son difíciles de revisar."))
    return checks


def _unavailable(reason: str) -> AuthorshipReview:
    return AuthorshipReview(available=False, reason=reason, verdict="no_disponible", headline=reason, limits=_limits(False))


def _limits(truncated: bool) -> list[str]:
    out = [
        "La IA solo se detecta cuando deja huella en git (coautoría en el mensaje, autor-agente) o en archivos de configuración. El código pegado desde un chat sin marcas "
        "es indistinguible del escrito a mano: por eso el porcentaje de IA es un MÍNIMO, no una cifra exacta.",
        "No se usan «detectores de texto escrito por IA»: no son confiables y acusarían falsamente a quien escribe de forma ordenada.",
        "Los indicadores de estilo (commits grandes, mensajes largos) son compatibles con IA y con equipos humanos; se muestran aparte y no cuentan en el porcentaje.",
        "La autoría de cada línea vigente sale de git blame ignorando espacios: el código movido o reformateado masivamente se atribuye a quien lo movió.",
        "Un commit con coautoría de IA no dice cuánto escribió cada parte: se cuenta completo como asistido por IA.",
        "Los nombres de colaboradores vienen del historial (pueden ser alias o cuentas compartidas). No se muestran correos.",
        "«Intervención humana» mide ediciones posteriores y revisiones visibles en git. No puede ver revisiones hechas fuera del repositorio.",
    ]
    if truncated:
        out.append(f"El historial es muy largo: solo se analizaron los últimos {MAX_COMMITS} commits; lo anterior se cuenta como «humano / sin declarar».")
    return out


def build(root: Path, inv: Inventory, debt: list[DebtFinding], arch: Architecture) -> AuthorshipReview:
    if not (root / ".git").exists():
        return _unavailable("No se dispone del historial de git para medir la autoría.")
    if (root / ".git" / "shallow").exists():
        return _unavailable("El repositorio se descargó sin historial (demasiado grande o sin permiso): no se puede medir la autoría.")
    commits, truncated = _parse_log(root)
    if not commits:
        return _unavailable("No se pudo leer el historial de commits.")
    by_sha = {c.sha: c for c in commits}

    # ---- código vigente por commit (git blame) ----
    cands = [f for f in inv.files if not f.is_generated and f.size < 400_000 and (f.is_code or f.ext in CODE_EXT)]
    cands.sort(key=lambda f: (not f.is_code, -f.size))
    t0 = time.monotonic()
    survive: Counter[str] = Counter()
    file_cls: dict[str, Counter[str]] = {}
    blames: dict[str, dict[str, int]] = {}
    blamed_files: list[FileInfo] = []
    blame_truncated = False
    for fi in cands[:MAX_BLAME_FILES]:
        if time.monotonic() - t0 > BLAME_BUDGET_S:
            blame_truncated = True
            break
        counts = _blame(root, fi.rel)
        if not counts:
            continue
        blames[fi.rel] = counts
        fc: Counter[str] = Counter()
        for sha, n in counts.items():
            c = by_sha.get(sha)
            survive[sha] += n
            fc[c.cls if c else CLS_HUMAN] += n
        file_cls[fi.rel] = fc
        blamed_files.append(fi)
    if len(cands) > MAX_BLAME_FILES:
        blame_truncated = True
    test_files = {f.rel for f in blamed_files if f.is_test or TEST_RE.search(f.rel)}

    lines = Counter()
    for sha, n in survive.items():
        c = by_sha.get(sha)
        lines[c.cls if c else CLS_HUMAN] += n
    total = sum(lines.values())
    ai_lines = lines[CLS_AI_AUTHOR] + lines[CLS_AI_CO]
    ai_pct = _pct(ai_lines, total)

    # ---- herramientas ----
    tools: dict[str, AiTool] = {}
    for c in commits:
        if c.cls in (CLS_AI_AUTHOR, CLS_AI_CO):
            m = re.search(r"(?im)^co-authored-by:\s*([^<\n]+?)\s*(?:<|$)", c.body)
            t = tools.setdefault(c.tool, AiTool(tool=c.tool, commits=0, how_detected="Autor del commit" if c.cls == CLS_AI_AUTHOR else
                                                "Coautoría declarada en el mensaje del commit" + (f" («{m.group(1)[:40]}»)" if m else "")))
            t.commits += 1
            t.lines_surviving += survive.get(c.sha, 0)
            if len(t.samples) < 2:
                t.samples.append(f"{c.sha[:7]} · {_day(c.date)} · {c.subject[:90]}")
    artifacts = sorted({f"{label}: {f.rel}" for f in inv.files for rx, label in ARTIFACTS if rx.search(f.rel)})[:12]
    total_added = sum(c.added for c in commits)
    indicators = _build_indicators(commits, inv, total_added)

    # ---- veredicto ----
    n_ind = sum(1 for i in indicators if i.observed)
    if ai_pct >= 70:
        verdict, head = "ia_mayoritaria", f"Al menos el {ai_pct}% del código vigente fue escrito con IA declarada: es un desarrollo predominantemente generado por IA."
    elif ai_pct >= 25:
        verdict, head = "mixto", f"Entre el {ai_pct}% del código vigente tiene IA declarada: desarrollo mixto entre personas e IA."
    elif ai_lines > 0:
        verdict, head = "humano_con_apoyo_ia", f"Solo el {ai_pct}% del código vigente tiene IA declarada: desarrollo mayormente humano con apoyo puntual de IA."
    elif artifacts or n_ind >= 2:
        verdict, head = "senales_sin_atribucion", "No hay commits con IA declarada, pero hay señales de un flujo de trabajo con IA (archivos de configuración o patrones de commits). No se puede cuantificar."
    else:
        verdict, head = "sin_evidencia", "No hay evidencia de IA en el historial. Eso no descarta uso no declarado."
    if verdict in ("ia_mayoritaria", "mixto", "humano_con_apoyo_ia"):
        head += " Es un mínimo: la IA no declarada no se puede detectar."

    # ---- supervivencia ----
    ai_added = sum(c.added for c in commits if c.cls in (CLS_AI_AUTHOR, CLS_AI_CO))
    human_added = sum(c.added for c in commits if c.cls == CLS_HUMAN)

    # ---- intervención humana ----
    ai_files = [rel for rel, fc in file_cls.items() if sum(fc.values()) and (fc[CLS_AI_AUTHOR] + fc[CLS_AI_CO]) / sum(fc.values()) >= 0.5]
    human_commits = [c for c in commits if c.cls == CLS_HUMAN]
    ai_commits = [c for c in commits if c.cls in (CLS_AI_AUTHOR, CLS_AI_CO)]
    touched = 0
    for rel in ai_files:
        if any(c.cls == CLS_HUMAN and rel in c.files for c in human_commits):
            touched += 1
    touch_rate = touched / len(ai_files) if ai_files else 0
    ai_file_lines = sum(sum(file_cls[r].values()) for r in ai_files)
    human_in_ai = sum(file_cls[r][CLS_HUMAN] for r in ai_files)
    edit_share = human_in_ai / ai_file_lines if ai_file_lines else 0
    prs = sum(1 for c in commits if re.match(r"(?i)merge pull request|merge branch .* into|merged pr", c.subject))
    reviewed = sum(1 for c in commits if re.search(r"(?im)^(reviewed-by|approved-by|acked-by):", c.body))
    humans = {_identity_key(c) for c in commits if c.cls in (CLS_HUMAN, CLS_AI_CO)}
    facts: list[str] = []
    if ai_commits:
        solo = sum(1 for c in ai_commits if c.cls == CLS_AI_CO)
        facts.append(f"{len(human_commits)} de {len(commits)} commits ({_pct(len(human_commits), len(commits))}%) no declaran IA; {solo} commits con IA declarada los publicó una persona a su nombre.")
        facts.append(f"De {len(ai_files)} archivos que nacieron mayormente de IA, {touched} ({int(touch_rate * 100)}%) recibieron después al menos un commit humano.")
        facts.append(f"En esos archivos, {_pct(human_in_ai, ai_file_lines)}% de las líneas vigentes hoy son de personas.")
        if ai_added:
            facts.append(f"Del código agregado por commits con IA, {_pct(survive_sum(ai_commits, survive), ai_added)}% sigue vigente (el resto fue reescrito o eliminado).")
    co_humans: Counter[str] = Counter()
    for c in commits:
        for nm in re.findall(r"(?im)^co-authored-by:\s*([^<\n]+?)\s*<", c.body):
            nm = nm.strip()
            if nm and not any(rx.search(f"{nm} <x>") for _, rx in AI_TRAILERS) and not AI_IDENTITY.search(nm) and not BOT_IDENTITY.search(nm) and nm.lower() != c.author.lower():
                co_humans[nm] += 1
    if co_humans:
        facts.append("Coautores humanos declarados en los mensajes: " + ", ".join(f"{k} ({v} commit{'s' if v > 1 else ''})" for k, v in co_humans.most_common(5)) + ".")
    facts.append(f"{prs} fusiones de ramas/PR, {reviewed} commits con revisión explícita (Reviewed-by) y {len(humans)} persona(s) distintas en el historial.")
    if not ai_commits:
        level, text = "no_medible", "No hay código con IA declarada sobre el que medir la intervención humana."
    elif touch_rate >= 0.6 or edit_share >= 0.3:
        level, text = "alta", "Hay intervención humana sustancial: las personas editaron o reescribieron una parte importante del código que nació de la IA."
    elif touch_rate >= 0.25 or edit_share >= 0.1:
        level, text = "media", "Hay intervención humana parcial: parte del código de IA fue ajustada por personas, pero una porción importante se conserva tal como la entregó la IA."
    else:
        level, text = "baja", ("La intervención humana visible en git es baja: las personas aceptaron y publicaron el código de IA con pocas ediciones posteriores. "
                               "Pudieron revisarlo fuera del repositorio, pero no queda evidencia.")

    # ---- colaboradores ----
    agg: dict[str, dict] = {}
    for c in commits:
        key = _identity_key(c)
        a = agg.setdefault(key, dict(name=c.author, kind="persona" if c.cls in (CLS_HUMAN, CLS_AI_CO) else "ia" if c.cls == CLS_AI_AUTHOR else "bot",
                                     commits=0, ai=0, added=0, surv=0, surv_ai=0, surv_test=0, first=c.date, last=c.date, areas=Counter()))
        a["commits"] += 1
        a["added"] += c.added
        a["ai"] += 1 if c.cls in (CLS_AI_AUTHOR, CLS_AI_CO) else 0
        a["first"] = min(a["first"], c.date)
        a["last"] = max(a["last"], c.date)
        for rel, n in c.files.items():
            top = rel.split("/")[0] if "/" in rel else "(raíz)"
            if top in ("app", "src") and rel.count("/") >= 2:
                top = "/".join(rel.split("/")[:2])
            a["areas"][top] += n
        n_surv = survive.get(c.sha, 0)
        a["surv"] += n_surv
        if c.cls in (CLS_AI_AUTHOR, CLS_AI_CO):
            a["surv_ai"] += n_surv
    # líneas vigentes en pruebas por colaborador
    for rel in test_files:
        if rel in blames:
            for sha, n in blames[rel].items():
                c = by_sha.get(sha)
                if c:
                    agg[_identity_key(c)]["surv_test"] += n
    collabs: list[Collaborator] = []
    for a in sorted(agg.values(), key=lambda x: -x["surv"]):
        collabs.append(Collaborator(
            name=a["name"], kind=a["kind"], commits=a["commits"], ai_declared_commits=a["ai"], lines_added=a["added"], lines_surviving=a["surv"],
            codebase_share_pct=_pct(a["surv"], total), survival_pct=_pct(a["surv"], a["added"]), ai_share_pct=_pct(a["surv_ai"], a["surv"]),
            test_share_pct=_pct(a["surv_test"], a["surv"]), first_commit=_day(a["first"]), last_commit=_day(a["last"]),
            top_areas=[k for k, _ in a["areas"].most_common(3)]))

    # ---- calidad por origen ----
    dominant: dict[str, str] = {}
    for rel, fc in file_cls.items():
        ai_n = fc[CLS_AI_AUTHOR] + fc[CLS_AI_CO]
        dominant[rel] = "IA declarada" if ai_n * 2 >= sum(fc.values()) and ai_n > 0 else "Humano / sin declarar"
    debt_files = {e.file for d in debt for e in d.evidence}
    quality: list[OriginQuality] = []
    for origin in ("IA declarada", "Humano / sin declarar"):
        files = [r for r, o in dominant.items() if o == origin]
        n_lines = sum(sum(file_cls[r].values()) for r in files)
        n_test = sum(sum(file_cls[r].values()) for r in files if r in test_files)
        quality.append(OriginQuality(origin=origin, lines=n_lines, share_pct=_pct(n_lines, total), files_over_600=sum(1 for r in files if sum(file_cls[r].values()) > 600),
                                     test_share_pct=_pct(n_test, n_lines), debt_evidence_files=len([r for r in files if r in debt_files])))

    # ---- bases tecnológicas ----
    found = _foundations(inv, debt, arch)
    passed = sum(1 for f in found if f.passed)
    ratio = passed / len(found)
    no_tests = not next(f for f in found if f.label == "Pruebas automáticas").passed
    sec_fail = not next(f for f in found if f.label.startswith("Sin riesgos de seguridad")).passed
    f_level = "solidas" if ratio >= 0.75 and not no_tests and not sec_fail else "fragiles" if ratio < 0.5 or (no_tests and sec_fail) else "aceptables"
    miss = [f.label.lower() for f in found if not f.passed]
    f_text = {"solidas": f"Las bases son sólidas ({passed}/{len(found)} prácticas): hay red de seguridad para evolucionar el sistema con o sin IA.",
              "aceptables": f"Las bases son aceptables ({passed}/{len(found)} prácticas), con huecos por cerrar: {', '.join(miss)}.",
              "fragiles": f"Las bases son frágiles ({passed}/{len(found)} prácticas). Faltan: {', '.join(miss)}. Así el código «funciona» hoy, pero cambiarlo es riesgoso."}[f_level]
    if ai_pct >= 25 and f_level != "solidas":
        f_text += " Con mucho código de IA, estas carencias son las que más suelen costar después."

    firsts = min(c.date for c in commits)
    lasts = max(c.date for c in commits)
    review = AuthorshipReview(
        available=True, verdict=verdict, headline=head, commits=len(commits), collaborators_count=len([c for c in collabs if c.kind == "persona"]),  # type: ignore[arg-type]
        first_commit=_day(firsts), last_commit=_day(lasts), truncated=truncated or blame_truncated, lines_analyzed=total, lines_ai=ai_lines,
        lines_human=lines[CLS_HUMAN], lines_bot=lines[CLS_BOT], ai_pct=ai_pct, ai_authored_pct=_pct(lines[CLS_AI_AUTHOR], total), ai_coauthored_pct=_pct(lines[CLS_AI_CO], total),
        ai_added_total=ai_added, ai_survived=survive_sum(ai_commits, survive), human_added_total=human_added, human_survived=survive_sum(human_commits, survive),
        tools=sorted(tools.values(), key=lambda t: -t.lines_surviving), artifacts=artifacts, indicators=indicators,
        intervention_level=level, intervention_text=text, intervention_facts=facts,  # type: ignore[arg-type]
        collaborators=collabs, quality=quality, foundations_level=f_level, foundations_text=f_text, foundations=found,  # type: ignore[arg-type]
        limits=_limits(truncated or blame_truncated))
    return review


def survive_sum(commits: list[Commit], survive: Counter) -> int:
    return sum(survive.get(c.sha, 0) for c in commits)
