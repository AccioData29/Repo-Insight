"""Utilidades compartidas: inventario de archivos, redacción de secretos y humanización de código."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .. import config
from ..models import Evidence

SKIP_DIRS = {
    ".git", "node_modules", "bin", "obj", "dist", "build", "out", "target", ".idea", ".vs", "__pycache__",
    ".venv", "venv", "env", "packages", "vendor", "coverage", ".next", ".angular", ".gradle", ".mypy_cache",
    ".pytest_cache", "bower_components", ".nuget", "TestResults", "wwwroot/lib",
}

LANG_BY_EXT = {
    ".cs": "C#", ".vb": "VB.NET", ".java": "Java", ".kt": "Kotlin", ".scala": "Scala", ".py": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".go": "Go", ".rb": "Ruby", ".php": "PHP", ".rs": "Rust", ".cpp": "C++", ".c": "C", ".swift": "Swift",
    ".sql": "SQL", ".cshtml": "Razor", ".razor": "Razor", ".html": "HTML", ".vue": "Vue", ".m": "MATLAB/Obj-C",
}
CODE_LANGS = {"C#", "VB.NET", "Java", "Kotlin", "Scala", "Python", "TypeScript", "JavaScript", "Go", "Ruby",
              "PHP", "Rust", "C++", "C", "Swift", "Vue"}
BRACE_LANGS = {"C#", "Java", "Kotlin", "Scala", "TypeScript", "JavaScript", "Go", "PHP", "Rust", "C++", "C", "Swift", "Vue"}

CONFIG_RE = re.compile(
    r"(?i)(^|/)(appsettings[^/]*\.json|web\.config|app\.config|[^/]*\.config|\.env[^/]*|[^/]*\.properties|"
    r"application[^/]*\.ya?ml|bootstrap[^/]*\.ya?ml|docker-compose[^/]*\.ya?ml|[^/]*\.tfvars|secrets?\.json|"
    r"config[^/]*\.(json|ya?ml|ini|toml)|settings[^/]*\.(json|py|ya?ml))$")
TEST_RE = re.compile(r"(?i)(^|/)(tests?|__tests__|spec|specs|unittests?|integrationtests?|e2e)(/|$)|"
                     r"(\.|_)(test|tests|spec)\.[a-z]+$|(^|/)test_[^/]*\.py$|[^/]*Tests?\.(cs|java|kt)$")
GENERATED_RE = re.compile(r"(?i)(\.designer\.cs|\.g\.cs|\.generated\.|\.min\.js|modelsnapshot\.cs|/migrations/|"
                          r"package-lock\.json|yarn\.lock|pnpm-lock\.yaml|reference\.cs|swagger|\.d\.ts)$|/migrations/")


@dataclass
class FileInfo:
    rel: str
    path: Path
    ext: str
    lang: Optional[str]
    size: int
    is_config: bool
    is_test: bool
    is_generated: bool

    @property
    def is_code(self) -> bool:
        return self.lang in CODE_LANGS

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


class Inventory:
    def __init__(self, root: Path):
        self.root = root
        self.files: list[FileInfo] = []
        self.artifacts: dict[str, int] = {}      # carpetas de compilados/dependencias versionadas
        self.dirs: set[str] = set()              # nombres de carpetas (minúscula)
        self.top_level: list[str] = []
        self.truncated = False
        self._cache: dict[str, str] = {}
        self._cache_bytes = 0
        self._scan()

    def _scan(self) -> None:
        root = str(self.root)
        self.top_level = sorted(
            [e.name + ("/" if e.is_dir() else "") for e in os.scandir(root) if e.name != ".git"],
            key=lambda s: (not s.endswith("/"), s.lower()))[:40]
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            keep = []
            for d in dirnames:
                if d in SKIP_DIRS:
                    if d in ("node_modules", "obj"):
                        self.artifacts[d] = self.artifacts.get(d, 0) + 1
                    elif d == "bin":
                        for _, _, fs in os.walk(os.path.join(dirpath, d)):
                            if any(f.lower().endswith((".dll", ".exe")) for f in fs):
                                self.artifacts["bin (binarios .dll/.exe)"] = self.artifacts.get("bin (binarios .dll/.exe)", 0) + 1
                                break
                    continue
                keep.append(d)
                self.dirs.add(d.lower())
            dirnames[:] = keep
            for f in filenames:
                if len(self.files) >= config.MAX_FILES:
                    self.truncated = True
                    return
                p = Path(dirpath) / f
                rel = f if rel_dir == "." else f"{rel_dir}/{f}"
                ext = p.suffix.lower()
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                self.files.append(FileInfo(
                    rel=rel, path=p, ext=ext, lang=LANG_BY_EXT.get(ext), size=size,
                    is_config=bool(CONFIG_RE.search(rel)), is_test=bool(TEST_RE.search(rel)),
                    is_generated=bool(GENERATED_RE.search(rel))))

    # ---------- lectura de texto con caché acotada ----------
    def text(self, fi: FileInfo) -> str:
        if fi.rel in self._cache:
            return self._cache[fi.rel]
        if fi.size > config.MAX_FILE_BYTES:
            return ""
        try:
            raw = fi.path.read_bytes()
        except OSError:
            return ""
        if b"\x00" in raw[:4096]:
            return ""
        txt = raw.decode("utf-8", errors="replace").lstrip("﻿")
        if fi.size > 100_000 and txt.count("\n") * 400 < len(txt):    # minificado
            return ""
        if self._cache_bytes < 150 * 1024 * 1024:
            self._cache[fi.rel] = txt
            self._cache_bytes += len(txt)
        return txt

    def lines(self, fi: FileInfo) -> list[str]:
        return self.text(fi).splitlines()

    def iter_files(self, *, code: bool = False, config_: bool = False, lang: Optional[set[str]] = None,
                   tests: bool = False, generated: bool = False, ext: Optional[tuple[str, ...]] = None,
                   name_re: Optional[re.Pattern] = None) -> Iterator[FileInfo]:
        for fi in self.files:
            if not tests and fi.is_test:
                continue
            if not generated and fi.is_generated:
                continue
            if lang is not None and fi.lang not in lang:
                continue
            if ext is not None and fi.ext not in ext:
                continue
            if name_re is not None and not name_re.search(fi.rel):
                continue
            if (code and fi.is_code) or (config_ and fi.is_config) or (not code and not config_):
                yield fi

    def find(self, pattern: str) -> list[FileInfo]:
        rx = re.compile(pattern, re.I)
        return [f for f in self.files if rx.search(f.rel)]

    def corpus_has(self, regex: re.Pattern, *, code_and_config: bool = True) -> bool:
        for fi in self.files:
            if fi.is_generated:
                continue
            if code_and_config and not (fi.is_code or fi.is_config or fi.ext in (".csproj", ".json", ".yml", ".yaml", ".xml", ".txt", ".gradle")):
                continue
            if regex.search(self.text(fi)):
                return True
        return False


# ----------------------------------------------------------------------------
# Redacción: ningún secreto debe aparecer jamás en el informe
# ----------------------------------------------------------------------------
_REDACT = [
    (re.compile(r"(?i)((?:password|passwd|pwd|secret|apikey|api_key|accesskey|access_key|token|clientsecret|privatekey)\w*"
                r"[\"']?\s*[=:]\s*[\"']?)([^\"';,\s}]{3,})"), r"\1***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[AWS-KEY]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"), "[GITHUB-TOKEN]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[SLACK-TOKEN]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[ANTHROPIC-KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[GOOGLE-KEY]"),
    (re.compile(r"://([^/:@\s\"']+):([^/@\s\"']+)@"), r"://\1:***@"),
]


def redact(s: str) -> str:
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    return s


def snippet(line: str, limit: int = 180) -> str:
    s = re.sub(r"\s+", " ", line.strip())
    s = redact(s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def ev(fi: FileInfo, lineno: int, line: str) -> Evidence:
    return Evidence(file=fi.rel, line=lineno, snippet=snippet(line))


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ----------------------------------------------------------------------------
# Humanización de identificadores y condiciones
# ----------------------------------------------------------------------------
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|_+|-+")


def words(ident: str) -> str:
    ident = ident.strip("_ ")
    parts = [p for p in _CAMEL.split(ident) if p]
    return " ".join(p.lower() if not p.isupper() or len(p) <= 3 else p for p in parts).strip()


def sentence(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


_KEYWORDS = {"true": "verdadero", "false": "falso", "null": "vacío", "none": "vacío", "nil": "vacío",
             "undefined": "vacío", "this": "", "self": "", "not": "no", "and": "y", "or": "o", "is": "es", "in": "en"}


def humanize_condition(cond: str) -> str:
    s = cond.strip()
    s = re.sub(r"\s+", " ", s)
    # lambdas: coleccion.Any(x => x.Campo == v)  ->  "alguno de coleccion cumple (Campo == v)"
    def _lambda(m: re.Match) -> str:
        coll, fn, var, body = m.group(1), m.group(2), m.group(3), m.group(4)
        body = re.sub(rf"\b{re.escape(var)}\.", "", body)
        word = {"Any": "alguno", "All": "todos", "Exists": "alguno", "any": "alguno", "all": "todos"}.get(fn, "alguno")
        return f"{word} de {coll} cumple ({body})"
    s = re.sub(r"([\w.]+)\.(Any|All|Exists|any|all)\(\s*\(?(\w+)\)?\s*=>\s*(.*)\)", _lambda, s)
    # comparaciones con null y negaciones frecuentes
    s = re.sub(r"([\w.]+)\s*(?:==|is)\s*(?:null|None)\b", r"\1 zznovalor", s)
    s = re.sub(r"([\w.]+)\s*(?:!=|is not)\s*(?:null|None)\b", r"\1 zzsivalor", s)
    s = re.sub(r"!\s*([\w.]+)\.Succeeded\b", r"\1 zzfallo", s)

    def tok(m: re.Match) -> str:
        t = m.group(0)
        low = t.lower()
        if low in _KEYWORDS:
            return _KEYWORDS[low]
        segs = [x for x in t.split(".") if x and x not in ("this", "self", "_")]
        if not segs:
            return ""
        if len(segs) == 1:
            return words(segs[0])
        last, prev = segs[-1], segs[-2]
        if prev[:1].isupper() and last[:1].isupper() and len(segs) == 2:
            return f"«{words(last)}»"                     # constante / enum
        if last in ("Count", "Length", "length", "size", "Size"):
            return f"cantidad de {words(prev)}"
        if last in ("Any", "any"):
            return f"{words(prev)} tiene elementos"
        return f"{words(last)} de {words(prev)}"

    s = re.sub(r"[A-Za-z_][A-Za-z0-9_.]*", tok, s)
    s = s.replace("zznovalor", "no tiene valor").replace("zzsivalor", "tiene valor").replace("zzfallo", "falló")
    for pat, rep in [
        (r"\(\)", ""), (r"&&", " y "), (r"\|\|", " o "), (r"!==|!=", " es distinto de "), (r"===|==", " es igual a "),
        (r">=", " es mayor o igual que "), (r"<=", " es menor o igual que "), (r">", " es mayor que "),
        (r"<", " es menor que "), (r"!", "no "), (r"[(){}]", " "), (r"\s*=\s*", " es igual a "),
    ]:
        s = re.sub(pat, rep, s)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    return s


def module_of(rel: str) -> str:
    generic = {"src", "source", "sources", "app", "apps", "main", "java", "kotlin", "com", "org", "net", "lib", "libs",
               "controllers", "controller", "services", "service", "models", "model", "entities", "entity", "domain",
               "application", "infrastructure", "core", "common", "shared", "dto", "dtos", "api", "web", "backend",
               "frontend", "client", "server", "repositories", "repository", "data", "handlers", "validators",
               "components", "pages", "features", "modules", "internal", "pkg", "cmd", "util", "utils", "helpers"}
    parts = rel.split("/")[:-1]
    # preferir el primer segmento específico (p.ej. Facturacion.Api o 'billing')
    for p in parts:
        if p.lower() not in generic and not p.startswith("."):
            return re.sub(r"\.(Api|Web|Core|Domain|Application|Infrastructure|Services?)$", "", p) or p
    return "General"


BUSINESS_PATH = re.compile(r"(?i)(service|domain|business|rule|usecase|use_case|handler|manager|calculator|policy|"
                           r"validator|application|logic|workflow|processor|engine)")
