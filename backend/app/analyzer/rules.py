"""Extracción de reglas de negocio desde el código fuente.

Es un análisis ESTÁTICO y determinista: cada regla trae evidencia (archivo:línea), una redacción en lenguaje de negocio
y un nivel de confianza.  Fuentes de reglas:

  1. Validaciones declarativas (DataAnnotations, FluentValidation, Bean Validation, pydantic, class-validator, Angular, EF Core)
  2. Mensajes de negocio en excepciones y respuestas de error HTTP (el propio mensaje suele ser la regla)
  3. Condiciones con umbrales / estados dentro de capas de negocio
  4. Estados y transiciones (enums *Status/*Estado y asignaciones)
  5. Autorización: roles, políticas y accesos anónimos
  6. Procesos programados (cron, intervalos)
  7. Parámetros de negocio configurables (límites, plazos, porcentajes…)
  8. Restricciones en base de datos (CHECK / UNIQUE / FK)
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Optional

from ..models import Evidence, Rule
from .common import (BRACE_LANGS, BUSINESS_PATH, FileInfo, Inventory, ev, humanize_condition, line_of, module_of,
                     sentence, snippet, words)

CAT_VALID = "Validación de datos"
CAT_BIZ = "Restricción de negocio"
CAT_COND = "Condición / umbral"
CAT_STATE = "Estado y transición"
CAT_AUTH = "Autorización y roles"
CAT_SCHED = "Proceso programado"
CAT_PARAM = "Parámetro configurable"
CAT_DB = "Restricción en base de datos"
CAT_TECH = "Error técnico controlado"
_TECH_FAILURE_MSG = re.compile(r"(?i)\b(unable to|unexpected|failed|failure|could not|cannot load|error (?:confirming|loading|setting|occurred)|no se pudo|falló|error al|excepci[oó]n)\b")

CLASS_RE = re.compile(r"\b(?:class|record|struct|interface)\s+([A-Za-z_]\w*)")
_DECL_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|async|override|virtual|final|abstract|sealed|extern|unsafe|new|partial)\s+)*"
    r"([\w<>\[\],.?]+)\s+([A-Za-z_]\w*)\s*\(")
_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(")
_JS_METHOD = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{\s*$")
_NOT_METHODS = {"if", "for", "foreach", "while", "switch", "catch", "using", "return", "lock", "else", "new", "throw", "await",
                "function", "constructor"}
_STATEMENT_TYPES = {"return", "new", "await", "throw", "else", "yield", "case", "in", "is", "as", "using", "var", "delete", "typeof", "not"}
_GENERIC_METHODS = {"execute", "executeasync", "run", "runasync", "handle", "handleasync", "invoke", "process", "main", "call", "start", "startasync"}


def method_name(line: str) -> str:
    """Nombre del método declarado en esta línea ('' si no es una declaración). Acepta cuerpos con `=>`."""
    s = line.strip()
    if not s or s.startswith(("//", "#", "*", "/*", "@", "[")):
        return ""
    m = _PY_DEF.match(line) or _JS_FUNC.match(line)
    if m:
        return m.group(1)
    m = _DECL_RE.match(line)
    if m:
        typ, name = m.group(1), m.group(2)
        if typ.lower() in _STATEMENT_TYPES or name in _NOT_METHODS:
            return ""
        if s.endswith(";") and "=>" not in s:      # llamada o declaración abstracta, no un cuerpo
            return ""
        return name
    m = _JS_METHOD.match(line)
    if m and m.group(1) not in _NOT_METHODS:
        return m.group(1)
    return ""


def pick_name(meth: str, cls: str) -> str:
    """Para métodos genéricos (ExecuteAsync, Run, Handle…) es más claro nombrar la clase."""
    if meth and meth.lower() in _GENERIC_METHODS and cls:
        return words(cls)
    return words(meth) or words(cls)


class RuleCollector:
    def __init__(self) -> None:
        self.rules: list[Rule] = []
        self._seen: set[tuple[str, int, str]] = set()

    def add(self, fi: FileInfo, line: int, raw: str, *, category: str, title: str, description: str,
            confidence: str = "alta", condition: Optional[str] = None, outcome: Optional[str] = None,
            tags: Optional[list[str]] = None) -> None:
        key = (fi.rel, line, category + title)
        if key in self._seen:
            return
        self._seen.add(key)
        self.rules.append(Rule(
            id="", category=category, module=module_of(fi.rel), title=title, description=description,
            condition=snippet(condition, 220) if condition else None, outcome=snippet(outcome, 160) if outcome else None,
            confidence=confidence,  # type: ignore[arg-type]
            evidence=ev(fi, line, raw), tags=tags or []))


# ------------------------------------------------------------------
# Contexto de clase/método a medida que se recorren las líneas
# ------------------------------------------------------------------
class _Ctx:
    """Contexto incremental (evita O(n²) en archivos largos)."""
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.cls = ""
        self.meth = ""
        self.i = 0

    def advance(self, to: int) -> None:
        while self.i < to and self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.lstrip().startswith(("//", "#", "*", "/*")):
                m = CLASS_RE.search(line)
                if m:
                    self.cls = m.group(1)
                name = method_name(line)
                if name:
                    self.meth = name
            self.i += 1


# =============================================================================
# 1. Validaciones declarativas
# =============================================================================
def _num(s: str) -> str:
    return s.strip().strip("\"'")


def _kwargs(args: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"(\w+)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[-\w.]+)", args or ""):
        out[m.group(1).lower()] = m.group(2).strip("\"'")
    return out


def _phrase(name: str, args: str) -> Optional[str]:
    a = (args or "").strip()
    kw = _kwargs(a)
    pos = [x.strip().strip("\"'") for x in re.split(r",(?![^(]*\))", a)] if a and "=" not in a.split(",")[0] else []
    n = name.lower()
    if n in ("required", "notnull", "notblank", "notempty", "isnotempty", "isdefined", "required_", "notnull()"):
        return "es obligatorio"
    if n in ("stringlength", "maxlength", "maximumlength", "max_length", "maxlen"):
        v = kw.get("maximumlength") or kw.get("max") or kw.get("max_length") or (pos[0] if pos else "")
        lo = kw.get("minimumlength")
        if v and lo:
            return f"debe tener entre {lo} y {v} caracteres"
        return f"admite como máximo {v} caracteres" if v else None
    if n in ("minlength", "minimumlength", "min_length"):
        v = kw.get("min") or kw.get("minimumlength") or kw.get("min_length") or (pos[0] if pos else "")
        return f"requiere al menos {v} caracteres" if v else None
    if n == "size":
        lo, hi = kw.get("min"), kw.get("max")
        if lo and hi:
            return f"debe tener entre {lo} y {hi} caracteres/elementos"
        if hi:
            return f"admite como máximo {hi} caracteres/elementos"
        if lo:
            return f"requiere al menos {lo} caracteres/elementos"
        return None
    if n in ("length",):
        return f"debe tener entre {pos[0]} y {pos[1]} caracteres" if len(pos) >= 2 else None
    if n == "range":
        return f"debe estar entre {pos[0]} y {pos[1]}" if len(pos) >= 2 else None
    if n == "inclusivebetween":
        return f"debe estar entre {pos[0]} y {pos[1]}" if len(pos) >= 2 else None
    if n in ("min", "greaterthanorequalto", "decimalmin", "ge", "min_value"):
        v = kw.get("value") or kw.get("ge") or (pos[0] if pos else "")
        return f"no puede ser menor que {v}" if v else None
    if n in ("max", "lessthanorequalto", "decimalmax", "le", "max_value"):
        v = kw.get("value") or kw.get("le") or (pos[0] if pos else "")
        return f"no puede ser mayor que {v}" if v else None
    if n in ("greaterthan", "gt"):
        v = kw.get("gt") or (pos[0] if pos else "")
        return f"debe ser mayor que {v}" if v else None
    if n in ("lessthan", "lt"):
        v = kw.get("lt") or (pos[0] if pos else "")
        return f"debe ser menor que {v}" if v else None
    if n in ("positive", "ispositive"):
        return "debe ser mayor que cero"
    if n == "positiveorzero":
        return "no puede ser negativo"
    if n == "negative":
        return "debe ser negativo"
    if n in ("email", "emailaddress", "isemail"):
        return "debe ser un correo electrónico válido"
    if n == "phone":
        return "debe ser un teléfono válido"
    if n == "url":
        return "debe ser una URL válida"
    if n == "creditcard":
        return "debe ser un número de tarjeta válido"
    if n in ("regularexpression", "pattern", "matches", "regex"):
        v = pos[0] if pos else kw.get("regexp") or kw.get("pattern") or kw.get("regex") or ""
        return f"debe cumplir el formato «{v}»" if v else "debe cumplir un formato específico"
    if n == "compare":
        return "debe coincidir con otro campo"
    if n in ("past", "pastorpresent"):
        return "debe ser una fecha pasada"
    if n in ("future", "futureorpresent"):
        return "debe ser una fecha futura"
    if n == "digits":
        return f"admite hasta {kw.get('integer', '?')} enteros y {kw.get('fraction', '?')} decimales"
    if n in ("unique", "isunique"):
        return "no puede repetirse (debe ser único)"
    if n in ("equal", "notequal"):
        return None
    return None


_CS_ATTR = re.compile(r"(Required|StringLength|MaxLength|MinLength|Range|RegularExpression|EmailAddress|Phone|Compare|Url|CreditCard)\b(?:\(((?:[^()]|\([^()]*\))*)\))?")
_JAVA_ATTR = re.compile(r"@(NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern|Email|Positive|PositiveOrZero|Negative|Past|PastOrPresent|Future|FutureOrPresent|DecimalMin|DecimalMax|Digits)\b(?:\(((?:[^()]|\([^()]*\))*)\))?")
_TS_ATTR = re.compile(r"@(IsNotEmpty|IsEmail|Min|Max|MinLength|MaxLength|IsPositive|Matches|IsDefined|Length)\b(?:\(((?:[^()]|\([^()]*\))*)\))?")
_CS_PROP = re.compile(r"^\s*public\s+(?:virtual\s+|required\s+)*[\w<>\[\]?,. ]+?\s+(\w+)\s*\{\s*get")
_JAVA_PROP = re.compile(r"^\s*(?:private|protected|public)\s+[\w<>\[\]?,. ]+?\s+(\w+)\s*(?:=[^;]*)?;")
_TS_PROP = re.compile(r"^\s*(?:public\s+|private\s+|readonly\s+)*(\w+)[!?]?\s*:\s*[\w<>\[\]| ]+;?")


def _validation_declarative(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True, lang={"C#", "Java", "Kotlin", "TypeScript"}):
        lines = inv.lines(fi)
        if not lines:
            continue
        ctx = _Ctx(lines)
        pending: list[tuple[str, str, int, str]] = []
        for idx, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue
            if fi.lang == "C#" and s.startswith("["):
                for m in _CS_ATTR.finditer(s):
                    pending.append((m.group(1), m.group(2) or "", idx + 1, line))
                continue
            if fi.lang in ("Java", "Kotlin") and s.startswith("@"):
                for m in _JAVA_ATTR.finditer(s):
                    pending.append((m.group(1), m.group(2) or "", idx + 1, line))
                continue
            if fi.lang == "TypeScript" and s.startswith("@"):
                for m in _TS_ATTR.finditer(s):
                    pending.append((m.group(1), m.group(2) or "", idx + 1, line))
                continue
            if s.startswith(("//", "/*", "*", "///")):
                continue
            if pending:
                pm = (_CS_PROP if fi.lang == "C#" else _JAVA_PROP if fi.lang in ("Java", "Kotlin") else _TS_PROP).match(line)
                if pm:
                    ctx.advance(idx)
                    field = pm.group(1)
                    phrases, first_line, first_raw = [], pending[0][2], pending[0][3]
                    msg = None
                    for name, args, ln, raw in pending:
                        ph = _phrase(name, args)
                        if ph:
                            phrases.append(ph)
                        mm = re.search(r"(?:ErrorMessage|message)\s*=\s*\"([^\"]{6,})\"", args)
                        if mm:
                            msg = re.sub(r"\{\d+\}", "…", mm.group(1))
                    if phrases:
                        cls = ctx.cls or "el formulario"
                        desc = f"El campo «{words(field)}» de «{words(cls)}» " + _join_phrases(phrases) + "."
                        if msg:
                            desc += f" Mensaje al usuario: «{msg}»."
                        rc.add(fi, first_line, first_raw, category=CAT_VALID,
                               title=f"{sentence(words(cls))}: {words(field)}", description=desc,
                               condition=" ".join(f"[{n}{'(' + a + ')' if a else ''}]" for n, a, _, _ in pending),
                               tags=["declarativa"])
                pending = []


def _join_phrases(ph: list[str]) -> str:
    uniq = list(OrderedDict.fromkeys(ph))
    return uniq[0] if len(uniq) == 1 else ", ".join(uniq[:-1]) + " y " + uniq[-1]


_FLUENT = re.compile(r"RuleFor\(\s*\w+\s*=>\s*\w+\.([\w.]+)\s*\)(.*?);", re.S)
_FLUENT_CALL = re.compile(r"\.(NotEmpty|NotNull|MaximumLength|MinimumLength|GreaterThanOrEqualTo|GreaterThan|LessThanOrEqualTo|LessThan|InclusiveBetween|EmailAddress|Matches|Length)\(((?:[^()]|\([^()]*\))*)\)")


def _validation_fluent(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True, lang={"C#"}):
        text = inv.text(fi)
        if "RuleFor" not in text:
            continue
        for m in _FLUENT.finditer(text):
            field, chain = m.group(1), m.group(2)
            ph = [p for c in _FLUENT_CALL.finditer(chain) if (p := _phrase(c.group(1), c.group(2)))]
            wm = re.search(r"WithMessage\(\s*\$?\"([^\"]{6,})\"", chain)
            if not ph and not wm:
                continue
            ln = line_of(text, m.start())
            cls = (CLASS_RE.findall(text[: m.start()]) or ["Validador"])[-1]
            desc = f"El campo «{words(field.split('.')[-1])}» " + (_join_phrases(ph) if ph else "debe cumplir una validación") + "."
            if wm:
                desc += f" Mensaje al usuario: «{re.sub(r'{\d+}', '…', wm.group(1))}»."
            rc.add(fi, ln, text.splitlines()[ln - 1], category=CAT_VALID, title=f"{sentence(words(cls))}: {words(field.split('.')[-1])}",
                   description=desc, condition=re.sub(r"\s+", " ", m.group(0))[:200], tags=["FluentValidation"])


_PYDANTIC = re.compile(r"^\s*(\w+)\s*:\s*[^=\n]+=\s*Field\((.*)\)\s*$")
_DJANGO = re.compile(r"^\s*(\w+)\s*=\s*models\.\w+Field\((.*)\)\s*$")
_ANGULAR = re.compile(r"Validators\.(required|min|max|minLength|maxLength|pattern|email|requiredTrue)\b(?:\(([^)]*)\))?")
_EF = re.compile(r"\.Property\(\s*\w+\s*=>\s*\w+\.(\w+)\s*\)((?:\s*\.\w+\((?:[^()]|\([^()]*\))*\))+)")
_EF_CALL = re.compile(r"\.(IsRequired|HasMaxLength|HasPrecision|IsUnicode)\(((?:[^()]|\([^()]*\))*)\)")


def _validation_other(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True, lang={"Python"}):
        lines = inv.lines(fi)
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            m = _PYDANTIC.match(line)
            if m:
                kw = _kwargs(m.group(2))
                ph = []
                for k in ("gt", "ge", "lt", "le", "min_length", "max_length", "pattern", "regex"):
                    if k in kw:
                        p = _phrase(k, f"{k}={kw[k]}")
                        if p:
                            ph.append(p)
                if "..." in m.group(2).split(",")[0]:
                    ph.insert(0, "es obligatorio")
                if ph:
                    ctx.advance(idx)
                    rc.add(fi, idx + 1, line, category=CAT_VALID, title=f"{sentence(words(ctx.cls))}: {words(m.group(1))}",
                           description=f"El campo «{words(m.group(1))}» de «{words(ctx.cls)}» {_join_phrases(ph)}.",
                           condition=f"Field({m.group(2)[:100]})", tags=["pydantic"])
                continue
            d = _DJANGO.match(line)
            if d:
                kw = _kwargs(d.group(2))
                ph = []
                if "max_length" in kw:
                    ph.append(f"admite como máximo {kw['max_length']} caracteres")
                if kw.get("unique", "").lower() == "true":
                    ph.append("no puede repetirse (debe ser único)")
                if ph:
                    ctx.advance(idx)
                    rc.add(fi, idx + 1, line, category=CAT_VALID, title=f"{sentence(words(ctx.cls))}: {words(d.group(1))}",
                           description=f"El campo «{words(d.group(1))}» de «{words(ctx.cls)}» {_join_phrases(ph)}.",
                           condition=snippet(line), tags=["Django"])
    for fi in inv.iter_files(code=True, lang={"TypeScript", "JavaScript"}):
        lines = inv.lines(fi)
        if not any("Validators." in l for l in lines):
            continue
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            ms = list(_ANGULAR.finditer(line))
            if not ms:
                continue
            ph = [p for m in ms if (p := _phrase(m.group(1), m.group(2) or ""))]
            fm = re.match(r"^\s*['\"]?(\w+)['\"]?\s*:", line) or re.search(r"(?:get|control)\(\s*['\"](\w+)['\"]", line)
            field = fm.group(1) if fm else "campo del formulario"
            if ph:
                ctx.advance(idx)
                rc.add(fi, idx + 1, line, category=CAT_VALID, title=f"Formulario: {words(field)}",
                       description=f"En pantalla, «{words(field)}» {_join_phrases(ph)}.", condition=snippet(line), tags=["Angular", "interfaz"])
    for fi in inv.iter_files(code=True, lang={"C#"}):
        text = inv.text(fi)
        if ".Property(" not in text and "IsUnique" not in text:
            continue
        for m in _EF.finditer(text):
            ph = []
            for c in _EF_CALL.finditer(m.group(2)):
                if c.group(1) == "IsRequired":
                    ph.append("es obligatorio")
                elif c.group(1) == "HasMaxLength":
                    ph.append(f"admite como máximo {c.group(2).strip()} caracteres")
            if ph:
                ln = line_of(text, m.start())
                rc.add(fi, ln, text.splitlines()[ln - 1], category=CAT_DB, title=f"Modelo de datos: {words(m.group(1))}",
                       description=f"En la base de datos, «{words(m.group(1))}» {_join_phrases(ph)}.", condition=snippet(m.group(0), 200), tags=["EF Core"])
        for m in re.finditer(r"\.HasIndex\(([^)]*)\)\s*\.IsUnique\(\)", text):
            ln = line_of(text, m.start())
            rc.add(fi, ln, text.splitlines()[ln - 1], category=CAT_DB, title="Valor único en base de datos",
                   description=f"La combinación {humanize_condition(m.group(1))} no puede repetirse en la base de datos.",
                   condition=snippet(m.group(0), 200), tags=["EF Core", "único"])


# =============================================================================
# 2. Mensajes de negocio en excepciones / respuestas HTTP
# =============================================================================
_IF_LINE = re.compile(r"^\s*(?:\}\s*)?(?:else\s+)?if\s*\((.*)\)\s*(?:\{\s*)?$")
_IF_PY = re.compile(r"^\s*(?:el)?if\s+(.*):\s*(?:#.*)?$")
_IF_INLINE = re.compile(r"if\s*\((.*)\)\s*(?:\{\s*)?(?:throw\s+new|return\s+\w*\.?(?:BadRequest|Conflict|UnprocessableEntity|Forbid))")
_THROW = re.compile(r"(?:throw\s+new|raise)\s+([A-Za-z_][\w.]*)\s*\(\s*(\$?@?[\"'`])(.+?)[\"'`]\s*[,)]")
_HTTPERR = [
    re.compile(r"return\s+(BadRequest|Conflict|UnprocessableEntity|NotFound|Forbid)\(\s*\$?\"([^\"]{8,})\""),
    re.compile(r"Results\.(BadRequest|Conflict|UnprocessableEntity|NotFound)\(\s*\$?\"([^\"]{8,})\""),
    re.compile(r"HTTPException\([^)]*status_code\s*=\s*(4\d\d)[^)]*detail\s*=\s*[\"']([^\"']{8,})"),
    re.compile(r"status\((4\d\d)\)\.(?:json|send)\(\s*\{?[^)]*?[\"'`]([^\"'`]{8,})[\"'`]"),
    re.compile(r"ResponseEntity\.(badRequest|status\(HttpStatus\.\w+\))\(\)\.body\(\s*\"([^\"]{8,})\""),
]
_TECH_EXC = re.compile(r"(?i)ArgumentNull|NotImplemented|NotSupported|InvalidCast|ObjectDisposed|OperationCanceled|NullReference|StopIteration|KeyError|IndexError|TypeError|AttributeError")
_TECH_MSG = re.compile(r"(?i)^(?:\w+\s+)?(?:cannot be null|must not be null|is required|not implemented|unexpected|invalid argument|null)\W*$")


def _find_condition(lines: list[str], idx: int, python: bool) -> Optional[str]:
    cur = lines[idx]
    m = _IF_INLINE.search(cur)
    if m:
        return m.group(1)
    if python:
        m = re.match(r"^\s*(?:el)?if\s+(.*?):\s*(?:raise|return)", cur)
        if m:
            return m.group(1)
    for back in range(1, 5):
        if idx - back < 0:
            break
        prev = lines[idx - back].rstrip()
        if not prev.strip() or prev.strip() in ("{", "}"):
            continue
        m = (_IF_PY if python else _IF_LINE).match(prev)
        if m:
            return m.group(1)
        if not prev.strip().startswith(("//", "#")):
            break
    return None


def _business_messages(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True):
        lines = inv.lines(fi)
        if not lines:
            continue
        python = fi.lang == "Python"
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            if len(line) > 500 or line.lstrip().startswith(("//", "#", "*")):
                continue
            msg = code = None
            m = _THROW.search(line)
            if m:
                exc, msg = m.group(1), m.group(3)
                if _TECH_EXC.search(exc) or _TECH_MSG.match(msg.strip()):
                    continue
                code = exc
            else:
                for rx in _HTTPERR:
                    hm = rx.search(line)
                    if hm:
                        code, msg = hm.group(1), hm.group(2)
                        break
            if not msg:
                continue
            msg = re.sub(r"\{[^}]*\}", "…", msg).strip()
            if len(msg) < 10 or " " not in msg:
                continue
            technical = bool(_TECH_FAILURE_MSG.search(msg))
            cond = _find_condition(lines, idx, python)
            ctx.advance(idx)
            human = humanize_condition(cond) if cond else None
            desc = f"El sistema rechaza la operación" + (f" cuando {human}" if human else "") + f" y responde: «{msg}»."
            rc.add(fi, idx + 1, line, category=CAT_TECH if technical else CAT_BIZ,
                   title=sentence(msg[:90]) + ("…" if len(msg) > 90 else ""), description=desc,
                   condition=cond, outcome=f"{code}: {msg}"[:160],
                   confidence="media" if technical or not cond else "alta",
                   tags=(["error técnico"] if technical else ["mensaje de negocio"]) + ([f"en {words(ctx.meth)}"] if ctx.meth else []))


_GUARD = {
    "null": "no puede ser nulo", "nullorempty": "no puede ser nulo ni vacío", "nullorwhitespace": "no puede ser nulo ni estar en blanco",
    "negative": "no puede ser negativo", "negativeorzero": "debe ser mayor que cero", "zero": "no puede ser cero",
    "outofrange": "debe estar dentro del rango permitido", "invalidformat": "debe cumplir el formato esperado",
    "default": "no puede tener el valor por defecto", "empty": "no puede estar vacío", "invalidinput": "debe cumplir la condición de validez",
}
_GUARD_RE = re.compile(r"Guard\.Against\.(\w+)(?:<[^>]*>)?\(\s*([\w.]+)")


def _guards(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True, lang={"C#"}):
        lines = inv.lines(fi)
        if not any("Guard.Against" in l for l in lines):
            continue
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            m = _GUARD_RE.search(line)
            if not m or line.lstrip().startswith("//"):
                continue
            kind = m.group(1).lower()
            phrase = _GUARD.get(kind) or ("no puede estar vacío" if kind.startswith("empty") else None)
            if not phrase:
                continue
            ctx.advance(idx)
            field = m.group(2).split(".")[-1]
            where = words(ctx.cls) or "el objeto"
            rc.add(fi, idx + 1, line, category=CAT_VALID, title=f"{sentence(where)}: {words(field)}",
                   description=f"Al crear o modificar «{where}», «{words(field)}» {phrase}.",
                   condition=snippet(line), tags=["cláusula de guarda"])


# =============================================================================
# 3. Condiciones con umbrales / estados
# =============================================================================
_INTERESTING = re.compile(r"(?<![\w.])(?:[2-9]\d*|1\d+)(?:\.\d+)?(?![\w.])|\b[A-Z]\w+\.[A-Z]\w+|==\s*[\"']\w+[\"']|\b(?:Estado|Status|Tipo|Type|Rol|Role)\w*", re.I)
_TRIVIAL = re.compile(r"(?i)\b(?:IsSuccessStatusCode|HttpStatusCode|StatusCode|IsValid|null|None|undefined|string\.IsNullOrEmpty|IsNullOrWhiteSpace|is None|is not None|typeof|instanceof|\.Count\s*[>=!]+\s*[01]\b|\.Length\s*[>=!]+\s*[01]\b|ModelState|\.Equals\(null\))")


_INFRA_NAME = re.compile(r"(?i)(cache|decorator|logger|logging|middleware|startup|program|telemetry|health|interop|toast)")


def _conditions(inv: Inventory, rc: RuleCollector, limit: int = 150) -> None:
    cands: list[tuple[int, FileInfo, int, str, str, str, str, str]] = []
    for fi in inv.iter_files(code=True):
        if fi.lang not in BRACE_LANGS and fi.lang not in ("Python",):
            continue
        lines = inv.lines(fi)
        if not lines:
            continue
        python = fi.lang == "Python"
        biz = bool(BUSINESS_PATH.search(fi.rel))
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            if len(line) > 300:
                continue
            m = (_IF_PY if python else _IF_LINE).match(line)
            if not m:
                continue
            cond = m.group(1)
            if len(cond) < 6 or _TRIVIAL.search(cond) or not _INTERESTING.search(cond) or re.search(r"\bout\s+(?:var|\w+)\b", cond):
                continue
            if _INFRA_NAME.search(fi.name):
                continue
            nums = re.findall(r"(?<![\w.])(?:[2-9]\d*|1\d+)(?:\.\d+)?(?![\w.])", cond)
            if not biz and not nums:
                continue
            # ¿esa condición ya fue capturada como excepción de negocio?
            nxt = next((lines[j] for j in range(idx + 1, min(idx + 4, len(lines))) if lines[j].strip() not in ("", "{")), "")
            if _THROW.search(nxt) or any(rx.search(nxt) for rx in _HTTPERR):
                continue
            ctx.advance(idx)
            score = (3 if biz else 0) + (2 if nums else 0) + (1 if re.search(r"[A-Z]\w+\.[A-Z]\w+", cond) else 0)
            cands.append((score, fi, idx + 1, line, cond, nxt.strip(), ctx.cls, ctx.meth))
    cands.sort(key=lambda c: -c[0])
    seen_cond: set[tuple[str, str]] = set()
    for score, fi, ln, raw, cond, nxt, cls, meth in cands[:limit * 2]:
        if (fi.rel, cond.strip()) in seen_cond:
            continue
        seen_cond.add((fi.rel, cond.strip()))
        if len(seen_cond) > limit:
            break
        human = humanize_condition(cond)
        where = f" (en «{words(meth)}»)" if meth else ""
        rc.add(fi, ln, raw, category=CAT_COND, title=sentence(human[:90]) + ("…" if len(human) > 90 else ""),
               description=f"El proceso toma un camino distinto cuando {human}{where}.",
               condition=cond, outcome=nxt or None, confidence="media" if score >= 3 else "baja", tags=["inferida"])


# =============================================================================
# 4. Estados y transiciones
# =============================================================================
_ENUM_BRACE = re.compile(r"\benum\s+(\w*(?:Status|Estado|State|Etapa|Fase|Tipo|Type)\w*)\s*(?::\s*\w+\s*)?\{([^}]*)\}", re.I)
_ASSIGN_STATE = re.compile(r"\.(\w*(?:Status|Estado|State|Etapa|Fase)\w*)\s*=\s*([A-Z]\w*\.\w+|[\"']\w+[\"'])\s*;?\s*$")


def _members(body: str) -> list[str]:
    out = []
    for part in body.split(","):
        p = re.sub(r"//.*|/\*.*?\*/|\[.*?\]|=.*$|\(.*\)", "", part, flags=re.S).strip()
        if re.match(r"^\w+$", p):
            out.append(p)
    return out


def _states(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True):
        text = inv.text(fi)
        if not text:
            continue
        if fi.lang in BRACE_LANGS:
            for m in _ENUM_BRACE.finditer(text):
                mem = _members(m.group(2))
                if 2 <= len(mem) <= 25:
                    ln = line_of(text, m.start())
                    rc.add(fi, ln, text.splitlines()[ln - 1], category=CAT_STATE, title=f"Estados de {words(m.group(1))}",
                           description=f"«{sentence(words(m.group(1)))}» puede estar en uno de estos valores: " + ", ".join(words(x) for x in mem) + ".",
                           condition=", ".join(mem), tags=["catálogo"])
        if fi.lang == "Python":
            for m in re.finditer(r"class\s+(\w*(?:Status|Estado|State|Etapa|Fase|Tipo|Type)\w*)\s*\((?:str\s*,\s*)?(?:Int)?Enum\)\s*:\s*\n((?:[ \t]+.*\n?)+)", text):
                mem = re.findall(r"^\s+(\w+)\s*=", m.group(2), re.M)
                if 2 <= len(mem) <= 25:
                    ln = line_of(text, m.start())
                    rc.add(fi, ln, text.splitlines()[ln - 1], category=CAT_STATE, title=f"Estados de {words(m.group(1))}",
                           description=f"«{sentence(words(m.group(1)))}» puede estar en uno de estos valores: " + ", ".join(words(x) for x in mem) + ".",
                           condition=", ".join(mem), tags=["catálogo"])
        lines = text.splitlines()
        ctx = _Ctx(lines)
        n = 0
        for idx, line in enumerate(lines):
            m = _ASSIGN_STATE.search(line)
            if m and n < 25 and not line.lstrip().startswith(("//", "#")):
                ctx.advance(idx)
                target = m.group(2).split(".")[-1].strip("\"'")
                rc.add(fi, idx + 1, line, category=CAT_STATE, title=f"Transición a «{words(target)}»",
                       description=f"En «{pick_name(ctx.meth, ctx.cls)}», el estado pasa a «{words(target)}».",
                       condition=snippet(line), confidence="media", tags=["transición"])
                n += 1


# =============================================================================
# 5. Autorización
# =============================================================================
def _next_target(lines: list[str], idx: int) -> str:
    for j in range(idx + 1, min(idx + 8, len(lines))):
        s = lines[j].strip()
        if not s or s.startswith(("[", "@", "//", "///")):
            continue
        m = CLASS_RE.search(s)
        if m:
            return words(m.group(1))
        name = method_name(lines[j])
        return words(name) if name else "este recurso"
    return "este recurso"


def _auth(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True):
        lines = inv.lines(fi)
        for idx, line in enumerate(lines):
            if len(line) > 300 or line.lstrip().startswith(("//", "#", "*")):
                continue
            s = line.strip()
            m = re.search(r"\[Authorize(?:\((.*?)\))?\]", s)
            if m:
                args = m.group(1) or ""
                roles = re.search(r"Roles\s*=\s*\"([^\"]+)\"", args)
                pol = re.search(r"Policy\s*=\s*\"([^\"]+)\"", args)
                tgt = _next_target(lines, idx)
                if roles:
                    desc = f"Solo los roles {roles.group(1).replace(',', ', ')} pueden acceder a «{tgt}»."
                elif pol:
                    desc = f"Para acceder a «{tgt}» se debe cumplir la política de seguridad «{pol.group(1)}»."
                else:
                    desc = f"Para acceder a «{tgt}» el usuario debe estar autenticado."
                rc.add(fi, idx + 1, line, category=CAT_AUTH, title=f"Acceso a {tgt}", description=desc, condition=s, tags=["acceso"])
                continue
            if "[AllowAnonymous]" in s:
                tgt = _next_target(lines, idx)
                rc.add(fi, idx + 1, line, category=CAT_AUTH, title=f"Acceso público a {tgt}",
                       description=f"«{tgt}» se puede usar sin iniciar sesión.", condition=s, tags=["acceso", "público"])
                continue
            m = re.search(r"@PreAuthorize\(\s*\"([^\"]+)\"|@RolesAllowed\(\s*\{?([^)}]*)\}?\s*\)|@Secured\(\s*\{?([^)}]*)\}?\s*\)", s)
            if m:
                expr = next(g for g in m.groups() if g)
                tgt = _next_target(lines, idx)
                rc.add(fi, idx + 1, line, category=CAT_AUTH, title=f"Acceso a {tgt}",
                       description=f"Para usar «{tgt}» se exige: {humanize_condition(expr.replace('hasRole', 'rol').replace('hasAnyRole', 'rol'))}.",
                       condition=s, tags=["acceso"])
                continue
            m = re.search(r"@permission_required\(\s*[\"']([^\"']+)|RequireRole\(\s*\"([^\"]+)\"|requireRole\(\s*['\"](\w+)", s)
            if m:
                role = next(g for g in m.groups() if g)
                rc.add(fi, idx + 1, line, category=CAT_AUTH, title=f"Requiere permiso «{role}»",
                       description=f"Esta operación exige el permiso/rol «{role}».", condition=s, tags=["acceso"])
            elif re.search(r"@login_required|Depends\(\s*get_current_\w+", s):
                rc.add(fi, idx + 1, line, category=CAT_AUTH, title="Requiere iniciar sesión",
                       description=f"«{_next_target(lines, idx)}» exige un usuario autenticado.", condition=s, confidence="media", tags=["acceso"])


# =============================================================================
# 6. Procesos programados
# =============================================================================
def _cron_human(expr: str) -> str:
    p = expr.split()
    if len(p) in (5, 6):
        if len(p) == 6:
            p = p[1:]
        mi, h, dom, mon, dow = p[:5]
        if mi.startswith("*/") and h == "*":
            return f"cada {mi[2:]} minutos"
        if h.startswith("*/") and mi.isdigit():
            return f"cada {h[2:]} horas"
        if mi.isdigit() and h.isdigit() and dom == "*" and mon == "*" and dow == "*":
            return f"todos los días a las {int(h):02d}:{int(mi):02d}"
        if mi.isdigit() and h.isdigit() and dow != "*":
            return f"los días de semana «{dow}» a las {int(h):02d}:{int(mi):02d}"
    return f"según la expresión cron «{expr}»"


_UNITS = {"Seconds": "segundos", "Minutes": "minutos", "Hours": "horas", "Days": "días"}


def _scheduled(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(code=True):
        lines = inv.lines(fi)
        ctx = _Ctx(lines)
        for idx, line in enumerate(lines):
            if len(line) > 400 or line.lstrip().startswith(("//", "#", "*")):
                continue
            desc = None
            m = re.search(r"@Scheduled\((.*)\)", line)
            if m:
                a = m.group(1)
                cm = re.search(r"cron\s*=\s*\"([^\"]+)\"", a)
                fm = re.search(r"fixed(?:Rate|Delay)\s*=\s*(\d+)", a)
                desc = f"Se ejecuta {_cron_human(cm.group(1))}" if cm else f"Se ejecuta cada {int(fm.group(1)) / 1000:g} segundos" if fm else None
            m = m or None
            if desc is None:
                m = re.search(r"WithCronSchedule\(\s*\"([^\"]+)\"|cron\.schedule\(\s*['\"]([^'\"]+)['\"]|CronExpression\(\s*\"([^\"]+)\"", line)
                if m:
                    desc = f"Se ejecuta {_cron_human(next(g for g in m.groups() if g))}"
            if desc is None:
                m = re.search(r"RecurringJob\.AddOrUpdate\(.*?(?:Cron\.(\w+)(?:\(([^)]*)\))?|\"([\d*/, ]{5,})\")", line)
                if m:
                    desc = f"Se ejecuta con frecuencia {m.group(1).lower() if m.group(1) else _cron_human(m.group(3))}"
            if desc is None:
                m = re.search(r"(?:Task\.Delay|PeriodicTimer)\(\s*TimeSpan\.From(Seconds|Minutes|Hours|Days)\(\s*(\d+)", line)
                if m:
                    desc = f"Se repite cada {m.group(2)} {_UNITS[m.group(1)]}"
            if desc is None:
                m = re.search(r"crontab\(([^)]*)\)", line)
                if m and ("celery" in inv.text(fi).lower() or "beat" in inv.text(fi).lower()):
                    desc = f"Se ejecuta según crontab({m.group(1)})"
            if desc:
                ctx.advance(idx)
                who = pick_name(ctx.meth, ctx.cls) or "tarea"
                rc.add(fi, idx + 1, line, category=CAT_SCHED, title=f"Proceso automático: {who}",
                       description=f"«{sentence(who)}» {desc[0].lower() + desc[1:]}.", condition=snippet(line), tags=["automático"])


# =============================================================================
# 7. Parámetros configurables
# =============================================================================
_PARAM_KEY = re.compile(r"(?i)(max|min|limit|limite|límite|umbral|threshold|dias|días|days|porcentaje|percent|tarifa|rate|plazo|vigencia|cantidad|quota|cupo|retention|retencion|ttl|expir|monto|tope|iva|tax|descuento|discount|interest|interes)")
_PARAM_SKIP = re.compile(r"(?i)(connectionstring|logging|loglevel|allowedhosts|password|secret|port$|^kestrel|urls?$|path$|version$)")


def _walk_json(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_json(v, f"{prefix}{k}:")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:10]):
            yield from _walk_json(v, f"{prefix}{i}:")
    else:
        yield prefix.rstrip(":"), obj


def _params(inv: Inventory, rc: RuleCollector) -> None:
    n = 0
    for fi in inv.iter_files(config_=True):
        if n > 80:
            break
        text = inv.text(fi)
        if not text:
            continue
        lines = text.splitlines()
        pairs: list[tuple[str, str]] = []
        if fi.ext == ".json":
            try:
                data = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))
                pairs = [(k, str(v)) for k, v in _walk_json(data) if isinstance(v, (int, float, bool)) or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v))]
            except Exception:
                pass
        else:
            for line in lines:
                m = re.match(r"^\s*([\w.\-:]+)\s*[=:]\s*(-?\d+(?:\.\d+)?|true|false)\s*(?:#.*)?$", line)
                if m:
                    pairs.append((m.group(1), m.group(2)))
        for key, val in pairs:
            last = key.split(":")[-1].split(".")[-1]
            if _PARAM_KEY.search(last) and not _PARAM_SKIP.search(key) and "development" not in fi.rel.lower():
                ln = next((i + 1 for i, l in enumerate(lines) if re.search(rf"(?<!\w){re.escape(last)}(?!\w)", l)), 1)
                rc.add(fi, ln, lines[ln - 1] if ln - 1 < len(lines) else key, category=CAT_PARAM, title=f"Parámetro: {words(last)} = {val}",
                       description=f"El valor de «{words(last)}» está definido en configuración como {val}; cambiarlo cambia la regla sin tocar el código.",
                       condition=f"{key} = {val}", confidence="media", tags=["configuración"])
                n += 1


# =============================================================================
# 8. SQL
# =============================================================================
def _sql(inv: Inventory, rc: RuleCollector) -> None:
    for fi in inv.iter_files(ext=(".sql",)):
        lines = inv.lines(fi)
        for idx, line in enumerate(lines):
            if re.match(r"^\s*--", line):
                continue
            for m in re.finditer(r"(?i)CHECK\s*\(((?:[^()]|\([^()]*\))*)\)", line):
                rc.add(fi, idx + 1, line, category=CAT_DB, title="Restricción CHECK",
                       description=f"La base de datos solo acepta registros donde {humanize_condition(m.group(1))}.",
                       condition=m.group(1), tags=["SQL"])
            if re.search(r"(?i)\bUNIQUE\b", line):
                col = re.search(r"(?i)(\w+)\s+[\w()]+\s+UNIQUE\b|UNIQUE\s*(?:\w+\s*)?\(([^)]*)\)", line)
                what = words(next((g for g in (col.groups() if col else ()) if g), "")) if col else ""
                rc.add(fi, idx + 1, line, category=CAT_DB, title="Valor único",
                       description=(f"«{what}» no puede repetirse entre registros (restricción UNIQUE)."
                                    if what else "Un valor no puede repetirse entre registros (restricción UNIQUE)."),
                       condition=snippet(line), confidence="media", tags=["SQL"])
            m2 = re.search(r"(?i)REFERENCES\s+([\w.\[\]\"]+)", line)
            if m2:
                target = words(m2.group(1).strip('[]"'))
                rc.add(fi, idx + 1, line, category=CAT_DB, title="Integridad referencial",
                       description=f"Un registro solo puede existir si el registro relacionado en «{target}» existe.",
                       condition=snippet(line), confidence="media", tags=["SQL"])


# =============================================================================
def extract_rules(inv: Inventory) -> list[Rule]:
    rc = RuleCollector()
    for step in (_validation_declarative, _validation_fluent, _validation_other, _guards, _business_messages, _auth,
                 _scheduled, _states, _sql, _params, _conditions):
        try:
            step(inv, rc)
        except Exception as exc:                      # un extractor defectuoso no debe tumbar el análisis
            rc.rules.append(Rule(id="", category="Herramienta", module="General", title=f"Extractor {step.__name__} falló",
                                 description=str(exc)[:200], confidence="baja",
                                 evidence=Evidence(file="(herramienta)", line=0, snippet=step.__name__)))
    order = {CAT_BIZ: 0, CAT_VALID: 1, CAT_AUTH: 2, CAT_STATE: 3, CAT_COND: 4, CAT_SCHED: 5, CAT_PARAM: 6, CAT_DB: 7, CAT_TECH: 8}
    conf = {"alta": 0, "media": 1, "baja": 2}
    rules = sorted(rc.rules, key=lambda r: (order.get(r.category, 9), r.module.lower(), conf[r.confidence], r.evidence.file, r.evidence.line))
    for i, r in enumerate(rules, 1):
        r.id = f"R-{i:03d}"
    return rules
