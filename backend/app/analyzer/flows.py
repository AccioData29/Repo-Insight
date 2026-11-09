"""Flujos del sistema: puntos de entrada → capas → sistemas externos, con diagramas Mermaid y relato en lenguaje de negocio."""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from ..models import EntryPoint, Flow, FlowStep, Rule
from .common import FileInfo, Inventory, module_of, sentence, words
from .rules import method_name

LAYER_LABEL = {
    "controller": "Punto de entrada (API)",
    "worker": "Proceso en segundo plano",
    "service": "Lógica de negocio",
    "repository": "Acceso a datos",
    "integration": "Integración externa",
    "other": "Componente",
    "ui": "Pantalla",
}

_SUFFIX_LAYER = [
    (re.compile(r"(Controller|Resource|Endpoint|Endpoints|Router|Routes|View|ViewSet)$"), "controller"),
    (re.compile(r"(Consumer|Listener|Subscriber|Job|Worker|Scheduler|HostedService|BackgroundService|Task|Processor|Handler)$"), "worker"),
    (re.compile(r"(Service|Manager|UseCase|Interactor|Facade|Orchestrator|Engine|Calculator|Policy|Validator|Rules?|Command|Query|Workflow|Saga)$"), "service"),
    (re.compile(r"(Repository|Repo|Dao|DAO|DbContext|Store|Gateway|Persistence|Dal)$"), "repository"),
    (re.compile(r"(Client|Adapter|Connector|Proxy|Sender|Notifier|Api|Integration|Provider)$"), "integration"),
]
_PATH_LAYER = [
    (re.compile(r"(?i)(^|/)(controllers?|endpoints?|routes?|api|resources|views)/"), "controller"),
    (re.compile(r"(?i)(^|/)(consumers?|jobs?|workers?|background|listeners?|hosted)/"), "worker"),
    (re.compile(r"(?i)(^|/)(services?|usecases?|use_cases?|application|handlers?|commands?|queries|business|domain/services)/"), "service"),
    (re.compile(r"(?i)(^|/)(repositories|repository|persistence|dal|dao|data|infrastructure/data)/"), "repository"),
    (re.compile(r"(?i)(^|/)(clients?|integrations?|gateways?|adapters?|external|connectors?)/"), "integration"),
]
_MODEL_HINT = re.compile(r"(?i)(^|/)(models?|entities|entity|dtos?|contracts|viewmodels?|enums?|exceptions?|constants?|options|config(uration)?)(/|$)|(Dto|DTO|Request|Response|Model|ViewModel|Entity|Exception|Enum|Options|Settings|Config|Attribute|Extensions?|Helper|Utils?)$")

CLASS_DECL = re.compile(r"^\s*(?:export\s+)?(?:public\s+|internal\s+|abstract\s+|sealed\s+|partial\s+|static\s+|final\s+)*(?:class|interface|record)\s+([A-Za-z_]\w*)(.*)$")
IDENT = re.compile(r"[A-Za-z_]\w{2,}")


@dataclass
class Node:
    name: str
    file: FileInfo
    layer: str
    line: int = 1
    tokens: set[str] = field(default_factory=set)
    externals: set[str] = field(default_factory=set)


EXTERNAL_PATTERNS = [
    ("Base de datos", re.compile(r"DbContext|SqlConnection|NpgsqlConnection|MySqlConnection|OracleConnection|IDbConnection|JdbcTemplate|EntityManager|psycopg|sqlalchemy|SessionLocal|mongoose|MongoClient|\bknex\b|\bDapper\b|@Repository|SqlCommand|\.ExecuteSql")),
    ("API externa", re.compile(r"HttpClient|IHttpClientFactory|RestSharp|WebClient|RestTemplate|requests\.(?:get|post|put|delete)|\bhttpx\b|\baxios\b|\bfetch\(|urllib|HttpWebRequest|FeignClient")),
    ("Cola de mensajes", re.compile(r"RabbitMQ|IPublishEndpoint|ISendEndpoint|ServiceBusSender|KafkaProducer|\.send_task|BackgroundJob\.Enqueue|\.delay\(|apply_async|\bSQS\b|basic_publish|IBus\b|rabbitTemplate|kafkaTemplate")),
    ("Archivos / almacenamiento", re.compile(r"BlobServiceClient|BlobClient|AmazonS3|\bboto3\b|File\.(?:WriteAll|ReadAll|Create|Open)|IFormFile|\bmulter\b|FileStream|shutil\.|MultipartFile")),
    ("OCR", re.compile(r"(?i:tesseract|easyocr|paddleocr|tess4j|ironocr|computervision|documentintelligence|formrecognizer|textract)|(?<![A-Za-z])(?:OCR|Ocr)(?![a-z])")),
    ("Correo electrónico", re.compile(r"SmtpClient|MailKit|SendGrid|nodemailer|smtplib|JavaMailSender|MimeMessage")),
    ("Caché", re.compile(r"\bRedis\b|IMemoryCache|IDistributedCache|memcache|StackExchange\.Redis|@Cacheable")),
]
_URL_HOST = re.compile(r"""["'`]https?://([A-Za-z0-9][\w.\-]+\.[A-Za-z]{2,})""")
_IGNORE_HOST = re.compile(r"(?i)(w3\.org|schemas\.|microsoft\.com/|xmlns|example\.(com|org)|localhost|json-schema|apache\.org|nuget\.org|github\.com/|swagger|openapis?\.org|googleapis\.com/auth)")


# ----------------------------------------------------------------------------
# Puntos de entrada
# ----------------------------------------------------------------------------
_HTTP_VERBS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH"}


def _norm_route(*parts: Optional[str]) -> str:
    segs = [p.strip("/") for p in parts if p and p.strip("/")]
    return "/" + "/".join(segs) if segs else "/"


def find_entry_points(inv: Inventory) -> list[EntryPoint]:
    eps: list[EntryPoint] = []

    def add(kind, method, route, name, fi, line):
        eps.append(EntryPoint(id="", kind=kind, method=method, route=route, name=name, file=fi.rel, line=line))

    for fi in inv.iter_files(code=True):
        lines = inv.lines(fi)
        if not lines:
            continue
        text = "\n".join(lines)
        lang = fi.lang
        if lang == "C#":
            cls, base = "", ""
            for i, line in enumerate(lines, 1):
                s = line.strip()
                m = re.search(r"\bclass\s+(\w+)", s)
                if m:
                    cls = m.group(1)
                    # [Route("api/[controller]")] suele estar 1-3 líneas arriba
                    ctx = " ".join(lines[max(0, i - 5): i])
                    rm = re.search(r"\[Route\(\s*\"([^\"]*)\"", ctx)
                    base = (rm.group(1) if rm else "").replace("[controller]", re.sub(r"Controller$", "", cls).lower())
                    if re.search(r"BackgroundService|IHostedService", s):
                        add("Proceso en segundo plano", None, None, cls, fi, i)
                    if re.search(r"IConsumer<|IMessageHandler|IRequestHandler<", s):
                        add("Consumidor / manejador", None, None, cls, fi, i)
                m = re.search(r"\[Http(Get|Post|Put|Delete|Patch)(?:\(\s*\"([^\"]*)\")?", s)
                if m and cls:
                    mname = next((method_name(l) for l in lines[i:i + 10] if method_name(l)), "")
                    route = _norm_route(base, m.group(2)).replace("[action]", mname.lower() or "[action]")
                    add("API", m.group(1).upper(), route, f"{cls}.{mname or '?'}", fi, i)
                m = re.search(r"\.Map(Get|Post|Put|Delete|Patch)\(\s*\"([^\"]*)\"", s)
                if m:
                    add("API", m.group(1).upper(), _norm_route(m.group(2)), f"{fi.name.rsplit('.', 1)[0]}", fi, i)
        elif lang in ("Java", "Kotlin"):
            cls, base = "", ""
            for i, line in enumerate(lines, 1):
                s = line.strip()
                m = re.search(r"\bclass\s+(\w+)", s)
                if m:
                    cls = m.group(1)
                    ctx = " ".join(lines[max(0, i - 4): i])
                    rm = re.search(r"@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\"([^\"]*)\"", ctx)
                    base = rm.group(1) if rm else ""
                m = re.search(r"@(Get|Post|Put|Delete|Patch)Mapping(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\"([^\"]*)\")?", s)
                if m and cls:
                    nxt = next((l for l in lines[i:i + 5] if re.search(r"\b\w+\s*\(", l) and not l.strip().startswith("@")), "")
                    mm = re.search(r"(\w+)\s*\(", nxt)
                    add("API", m.group(1).upper(), _norm_route(base, m.group(2)), f"{cls}.{mm.group(1) if mm else '?'}", fi, i)
                m = re.search(r"@(RabbitListener|KafkaListener|JmsListener|SqsListener)", s)
                if m:
                    add("Consumidor de cola", None, None, cls or fi.name, fi, i)
                if re.search(r"@Scheduled", s):
                    add("Proceso programado", None, None, cls or fi.name, fi, i)
        elif lang == "Python":
            for i, line in enumerate(lines, 1):
                s = line.strip()
                m = re.match(r"@(?:\w+)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']*)", s)
                if m:
                    nxt = next((l for l in lines[i:i + 4] if re.match(r"\s*(?:async\s+)?def\s+\w+", l)), "")
                    nm = re.search(r"def\s+(\w+)", nxt)
                    add("API", m.group(1).upper(), _norm_route(m.group(2)), nm.group(1) if nm else "?", fi, i)
                    continue
                m = re.match(r"@(?:\w+)\.route\(\s*[\"']([^\"']*)[\"'](?:\s*,\s*methods\s*=\s*\[([^\]]*)\])?", s)
                if m:
                    nxt = next((l for l in lines[i:i + 4] if re.match(r"\s*(?:async\s+)?def\s+\w+", l)), "")
                    nm = re.search(r"def\s+(\w+)", nxt)
                    methods = re.findall(r"[A-Za-z]+", m.group(2) or "GET")
                    add("API", "/".join(x.upper() for x in methods), _norm_route(m.group(1)), nm.group(1) if nm else "?", fi, i)
                    continue
                m = re.match(r"(?:re_)?path\(\s*[\"']([^\"']*)[\"']\s*,\s*([\w.]+)", s)
                if m and "urls" in fi.rel.lower():
                    add("API", None, _norm_route(m.group(1)), m.group(2), fi, i)
                    continue
                if re.match(r"@(?:\w+\.)?(?:task|shared_task)\b", s):
                    nxt = next((l for l in lines[i:i + 3] if re.match(r"\s*(?:async\s+)?def\s+\w+", l)), "")
                    nm = re.search(r"def\s+(\w+)", nxt)
                    add("Tarea en segundo plano", None, None, nm.group(1) if nm else "?", fi, i)
        elif lang in ("TypeScript", "JavaScript"):
            cls_ctrl = ""
            for i, line in enumerate(lines, 1):
                s = line.strip()
                m = re.match(r"@Controller\(\s*['\"]([^'\"]*)", s)
                if m:
                    cls_ctrl = m.group(1)
                m = re.match(r"@(Get|Post|Put|Delete|Patch)\(\s*(?:['\"]([^'\"]*)['\"])?", s)
                if m:
                    nxt = next((l for l in lines[i:i + 3] if re.search(r"\w+\s*\(", l)), "")
                    nm = re.search(r"(?:async\s+)?(\w+)\s*\(", nxt)
                    add("API", m.group(1).upper(), _norm_route(cls_ctrl, m.group(2)), nm.group(1) if nm else "?", fi, i)
                    continue
                m = re.search(r"\b(?:app|router|server)\.(get|post|put|delete|patch)\(\s*['\"`]([^'\"`]*)", s)
                if m:
                    add("API", m.group(1).upper(), _norm_route(m.group(2)), fi.name.rsplit(".", 1)[0], fi, i)
                    continue
                m = re.search(r"\{\s*path:\s*['\"]([^'\"]*)['\"]\s*,\s*component:\s*(\w+)", s)
                if m:
                    add("Pantalla", None, "/" + m.group(1).strip("/"), m.group(2), fi, i)
                    continue
                m = re.search(r"<Route\s+[^>]*path=[\"']([^\"']*)[\"'][^>]*element=\{<(\w+)", s)
                if m:
                    add("Pantalla", None, "/" + m.group(1).strip("/"), m.group(2), fi, i)
    seen = set()
    uniq = []
    for e in eps:
        k = (e.kind, e.method, e.route, e.name, e.file)
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    uniq.sort(key=lambda e: (e.kind != "API", e.kind, e.route or "", e.method or ""))
    for i, e in enumerate(uniq[:400], 1):
        e.id = f"EP-{i:03d}"
    return uniq[:400]


# ----------------------------------------------------------------------------
# Grafo de dependencias
# ----------------------------------------------------------------------------
def _layer_of(name: str, rel: str) -> str:
    if _MODEL_HINT.search(rel) and not any(rx.search(name) for rx, _ in _SUFFIX_LAYER):
        return "model"
    for rx, layer in _SUFFIX_LAYER:
        if rx.search(name):
            return layer
    for rx, layer in _PATH_LAYER:
        if rx.search(rel):
            return layer
    if _MODEL_HINT.search(name) or _MODEL_HINT.search(rel):
        return "model"
    return "other"


def build_graph(inv: Inventory) -> tuple[dict[str, Node], dict[str, set[str]]]:
    nodes: dict[str, Node] = {}
    alias_impls: dict[str, list[str]] = defaultdict(list)      # IFoo -> [clases que lo implementan]
    file_nodes: dict[str, Node] = {}
    for fi in inv.iter_files(code=True):
        if fi.lang not in ("C#", "Java", "Kotlin", "TypeScript", "JavaScript", "Python"):
            continue
        text = inv.text(fi)
        if not text:
            continue
        lines = text.splitlines()
        stem = fi.name.rsplit(".", 1)[0]
        classes: list[tuple[str, int, str]] = []
        if fi.lang == "Python":
            for i, line in enumerate(lines, 1):
                m = re.match(r"^class\s+(\w+)", line)
                if m:
                    classes.append((m.group(1), i, line))
        else:
            for i, line in enumerate(lines, 1):
                m = CLASS_DECL.match(line)
                if m:
                    classes.append((m.group(1), i, line))
        if fi.lang in ("C#", "Java", "Kotlin"):
            for name, _, line in classes:
                decl = line.split("{")[0]
                if re.search(r"\binterface\b", decl):          # una interfaz no se implementa a sí misma
                    continue
                tail = decl.split(name, 1)[-1]                   # solo lo que sigue al nombre de la clase
                tail = re.sub(r"\([^)]*\)", "", tail)            # quita parámetros del constructor primario (C# 12 / Kotlin)
                bm = re.search(r":|\bimplements\b|\bextends\b", tail)
                bases = tail[bm.end():] if bm else ""
                bases = re.split(r"\bwhere\b", bases)[0]
                while re.search(r"<[^<>]*>", bases):                # fuera argumentos genéricos: IEndpoint<A, IRepo<B>> -> IEndpoint
                    bases = re.sub(r"<[^<>]*>", "", bases)
                for iface in re.findall(r"(?<![\w.])(I[A-Z]\w+)", bases):
                    alias_impls[iface].append(name)
        primary = next((c for c in classes if c[0] == stem), None) or (classes[0] if classes else None)
        if primary:
            name, ln, _ = primary
        else:
            name, ln = stem, 1
        if name in nodes:
            name = f"{name}@{fi.rel}"
        layer = _layer_of(name.split("@")[0], fi.rel)
        node = Node(name=name, file=fi, layer=layer, line=ln)
        node.tokens = set(IDENT.findall(text))
        for label, rx in EXTERNAL_PATTERNS:
            if rx.search(text):
                node.externals.add(label)
        hosts = {h for h in _URL_HOST.findall(text) if not _IGNORE_HOST.search(h)}
        for h in list(hosts)[:2]:
            node.externals.add(f"API externa: {h}")
        nodes[name] = node
        file_nodes[fi.rel] = node
    names = {n.split("@")[0]: n for n in nodes}
    # una interfaz con UNA sola implementación se resuelve a esa clase (la que realmente toca la BD / el sistema externo).
    # Las interfaces con varias implementaciones (IEndpoint, IRequestHandler…) son ambiguas y no se resuelven.
    for iface, impls in alias_impls.items():
        uniq = list(dict.fromkeys(impls))
        if len(uniq) == 1 and uniq[0] in names:
            names[iface] = names[uniq[0]]
    edges: dict[str, set[str]] = defaultdict(set)
    for n in nodes.values():
        for tok in n.tokens:
            tgt = names.get(tok)
            if tgt and tgt != n.name:
                edges[n.name].add(tgt)
    return nodes, edges


# ----------------------------------------------------------------------------
# Generación de flujos
# ----------------------------------------------------------------------------
_BEHAVIOR = {"controller", "worker", "service", "repository", "integration", "other"}
_MAX_NODES = 14


def _bfs(start: str, nodes: dict[str, Node], edges: dict[str, set[str]]) -> list[tuple[str, int]]:
    order: list[tuple[str, int]] = []
    seen = {start}
    q = deque([(start, 0)])
    while q and len(order) < _MAX_NODES:
        cur, d = q.popleft()
        order.append((cur, d))
        if d >= 4:
            continue
        nxt = sorted(edges.get(cur, ()), key=lambda n: (nodes[n].layer != "service", nodes[n].layer != "repository", n))
        for t in nxt:
            tl = nodes[t].layer
            if t in seen or tl == "model":
                continue
            if tl == "other" and not nodes[t].externals:      # ruido: clases sin rol claro ni integración
                continue
            seen.add(t)
            q.append((t, d + 1))
    return order


def display_name(name: str) -> str:
    n = name.split("@")[0]
    return n[1:] if re.match(r"^I[A-Z][a-z]", n) else n


def _mid(name: str) -> str:
    return "n_" + re.sub(r"\W", "_", name)


def _label(s: str) -> str:
    return s.replace('"', "'").replace("<", "‹").replace(">", "›")


def _mermaid(order: list[tuple[str, int]], nodes: dict[str, Node], edges: dict[str, set[str]], ext: list[str]) -> str:
    ids = {n for n, _ in order}
    out = ["flowchart LR"]
    for name, _ in order:
        n = nodes[name]
        lab = _label(display_name(name))
        shape = {"controller": '(["{}"])', "worker": '(["{}"])', "repository": '[("{}")]', "integration": '{{{{"{}"}}}}'}.get(n.layer, '["{}"]')
        out.append(f"  {_mid(name)}{shape.format(lab)}:::{n.layer}")
    for i, e in enumerate(ext):
        out.append(f'  x{i}[["{_label(e)}"]]:::ext')
    for name, _ in order:
        for t in sorted(edges.get(name, ())):
            if t in ids and nodes[t].layer != "model":
                out.append(f"  {_mid(name)} --> {_mid(t)}")
    for name, _ in order:
        for i, e in enumerate(ext):
            if e in nodes[name].externals and nodes[name].layer in ("repository", "integration", "service", "worker", "controller"):
                out.append(f"  {_mid(name)} -.-> x{i}")
    out += [
        "  classDef controller fill:#d6ecf5,stroke:#2b7a99,color:#0b3b4d",
        "  classDef worker fill:#ece1f7,stroke:#7a4fb0,color:#2e1a4d",
        "  classDef service fill:#dff3e4,stroke:#3a8a4f,color:#123d1f",
        "  classDef repository fill:#fdecc8,stroke:#b8860b,color:#4a3600",
        "  classDef integration fill:#fbdcd5,stroke:#c0553a,color:#4d1a0e",
        "  classDef other fill:#eceff1,stroke:#78909c,color:#263238",
        "  classDef ext fill:#ffffff,stroke:#999,stroke-dasharray: 4 3,color:#333",
    ]
    return "\n".join(out)


def build_flows(inv: Inventory, entry_points: list[EntryPoint], rules: list[Rule],
                graph: Optional[tuple[dict[str, Node], dict[str, set[str]]]] = None, max_flows: int = 14) -> list[Flow]:
    nodes, edges = graph or build_graph(inv)
    file_to_node = {n.file.rel: n for n in nodes.values()}
    rules_by_file: dict[str, list[str]] = defaultdict(list)
    for r in rules:
        rules_by_file[r.evidence.file].append(r.id)

    groups: dict[str, list[EntryPoint]] = defaultdict(list)
    for ep in entry_points:
        if ep.kind == "Pantalla":
            continue
        groups[ep.file].append(ep)

    candidates: list[tuple[int, str, list[EntryPoint], list[tuple[str, int]]]] = []
    for file, eps in groups.items():
        start = file_to_node.get(file)
        if not start:
            continue
        order = _bfs(start.name, nodes, edges)
        candidates.append((len(order) * 10 + len(eps), start.name, eps, order))
    candidates.sort(key=lambda c: -c[0])

    flows: list[Flow] = []
    for score, start, eps, order in candidates[:max_flows]:
        node = nodes[start]
        ext_all: list[str] = []
        for n, _ in order:
            for e in sorted(nodes[n].externals):
                if e not in ext_all:
                    ext_all.append(e)
        if any(e.startswith("API externa: ") for e in ext_all):
            ext_all = [e for e in ext_all if e != "API externa"]
        ext_all = ext_all[:8]
        steps = []
        for i, (n, d) in enumerate(order, 1):
            nd = nodes[n]
            steps.append(FlowStep(order=i, layer=nd.layer, layer_label=LAYER_LABEL.get(nd.layer, "Componente"),
                                  name=display_name(n) if n.split("@")[0].startswith("I") and re.match(r"^I[A-Z][a-z]", n) else n.split("@")[0], file=nd.file.rel,
                                  description=f"{LAYER_LABEL.get(nd.layer, 'Componente')}: {words(display_name(n))}"))
        kind = eps[0].kind
        title_base = re.sub(r"(Controller|Resource|Endpoints?|Router)$", "", start.split("@")[0]) or start
        api = [e for e in eps if e.kind == "API"]
        uniq = list(dict.fromkeys(f"{e.method or ''} {e.route}".strip() for e in api))
        routes = ", ".join(uniq[:4])
        entry_name = words(start.split("@")[0])
        later = [s for s in steps[1:] if s.layer in ("service", "repository", "integration", "worker", "other")]
        if api:
            narrative = f"Cuando llega una solicitud a {routes}{' (y otras rutas)' if len(uniq) > 4 else ''}, «{entry_name}» recibe el trabajo"
        elif "programado" in kind.lower() or "segundo plano" in kind.lower() or "tarea" in kind.lower():
            narrative = f"El proceso automático «{entry_name}» se ejecuta sin intervención de un usuario"
        else:
            narrative = f"Cuando llega un mensaje o evento, «{entry_name}» lo recibe"
        if later:
            narrative += " y lo delega en " + ", ".join(f"«{s.description.split(': ', 1)[1]}» ({s.layer_label.lower()})" for s in later[:4])
        if ext_all:
            narrative += ". Interactúa con: " + ", ".join(ext_all[:5])
        narrative += "."
        rule_ids: list[str] = []
        for s in steps:
            rule_ids.extend(rules_by_file.get(s.file, []))
        flows.append(Flow(
            id="", title=f"{sentence(words(title_base))}" + (f" ({kind.lower()})" if kind != "API" else ""), kind=kind,
            narrative=narrative, mermaid=_mermaid(order, nodes, edges, ext_all), steps=steps, entry_points=eps[:20],
            externals=ext_all, rule_ids=list(dict.fromkeys(rule_ids))[:60]))
    for i, f in enumerate(flows, 1):
        f.id = f"F-{i:02d}"
    return flows


def layer_counts(nodes: dict[str, Node]) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for n in nodes.values():
        c[LAYER_LABEL.get(n.layer, "Modelos y utilidades") if n.layer != "model" else "Modelos / DTOs"] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))
