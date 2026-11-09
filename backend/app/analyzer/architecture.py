"""Arquitectura: lenguajes, frameworks, estilo, datos, mensajería, contenedores, CI/CD y diagrama."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from ..models import Architecture, LangStat
from .common import CODE_LANGS, Inventory, words
from .flows import Node, layer_counts

_PKG = {
    # .NET
    "microsoft.entityframeworkcore": ("Entity Framework Core", "framework"), "dapper": ("Dapper", "framework"),
    "mediatr": ("MediatR (CQRS/mediator)", "framework"), "fluentvalidation": ("FluentValidation", "framework"),
    "automapper": ("AutoMapper", "framework"), "hangfire": ("Hangfire", "framework"), "serilog": ("Serilog", "framework"),
    "masstransit": ("MassTransit", "framework"), "polly": ("Polly (resiliencia)", "framework"),
    "xunit": ("xUnit", "test"), "nunit": ("NUnit", "test"), "mstest": ("MSTest", "test"),
    "swashbuckle": ("Swagger/OpenAPI", "framework"), "microsoft.aspnetcore.identity": ("ASP.NET Identity", "auth"),
    "microsoft.aspnetcore.authentication.jwtbearer": ("JWT Bearer", "auth"), "identityserver": ("IdentityServer", "auth"),
    "npgsql": ("PostgreSQL", "db"), "microsoft.data.sqlclient": ("SQL Server", "db"), "system.data.sqlclient": ("SQL Server", "db"),
    "mysql": ("MySQL", "db"), "oracle.manageddataaccess": ("Oracle", "db"), "mongodb": ("MongoDB", "db"),
    "stackexchange.redis": ("Redis", "db"), "microsoft.data.sqlite": ("SQLite", "db"),
    "rabbitmq.client": ("RabbitMQ", "msg"), "confluent.kafka": ("Kafka", "msg"), "azure.messaging.servicebus": ("Azure Service Bus", "msg"),
    "awssdk": ("AWS SDK", "cloud"), "azure.": ("Azure SDK", "cloud"), "google.cloud": ("Google Cloud SDK", "cloud"),
    # JS
    "@angular/core": ("Angular", "framework"), "react": ("React", "framework"), "vue": ("Vue", "framework"),
    "express": ("Express", "framework"), "@nestjs/core": ("NestJS", "framework"), "next": ("Next.js", "framework"),
    "typeorm": ("TypeORM", "framework"), "prisma": ("Prisma", "framework"), "sequelize": ("Sequelize", "framework"),
    "jest": ("Jest", "test"), "jasmine-core": ("Jasmine", "test"), "mocha": ("Mocha", "test"), "pg": ("PostgreSQL", "db"),
    "mysql2": ("MySQL", "db"), "mongoose": ("MongoDB", "db"), "redis": ("Redis", "db"), "amqplib": ("RabbitMQ", "msg"),
    "kafkajs": ("Kafka", "msg"), "bullmq": ("BullMQ", "msg"), "passport": ("Passport", "auth"), "jsonwebtoken": ("JWT", "auth"),
    # Python
    "fastapi": ("FastAPI", "framework"), "flask": ("Flask", "framework"), "django": ("Django", "framework"),
    "sqlalchemy": ("SQLAlchemy", "framework"), "celery": ("Celery", "msg"), "pydantic": ("Pydantic", "framework"),
    "pytest": ("pytest", "test"), "psycopg2": ("PostgreSQL", "db"), "psycopg": ("PostgreSQL", "db"), "pymysql": ("MySQL", "db"),
    "pyodbc": ("SQL Server / ODBC", "db"), "pymongo": ("MongoDB", "db"), "pika": ("RabbitMQ", "msg"), "boto3": ("AWS SDK", "cloud"),
    "pandas": ("pandas", "framework"), "pytesseract": ("Tesseract OCR", "framework"), "tesseract": ("Tesseract OCR", "framework"),
    # Java
    "spring-boot-starter-web": ("Spring Boot", "framework"), "spring-boot": ("Spring Boot", "framework"),
    "hibernate": ("Hibernate/JPA", "framework"), "spring-boot-starter-security": ("Spring Security", "auth"),
    "postgresql": ("PostgreSQL", "db"), "mysql-connector": ("MySQL", "db"), "ojdbc": ("Oracle", "db"),
    "spring-kafka": ("Kafka", "msg"), "spring-rabbit": ("RabbitMQ", "msg"), "junit": ("JUnit", "test"), "tess4j": ("Tesseract OCR", "framework"),
}
_MANIFEST_EXT = (".csproj", ".vbproj", ".props", ".json", ".txt", ".toml", ".gradle", ".kts", ".xml", ".cfg")
_CONN_DB = [
    (re.compile(r"(?i)Host=|Server=.*;.*Port=5432|postgres(?:ql)?://"), "PostgreSQL"),
    (re.compile(r"(?i)Data Source=.*;.*Initial Catalog|Server=.*;.*Database=|mssql|sqlserver"), "SQL Server"),
    (re.compile(r"(?i)mysql://|Server=.*;.*Uid="), "MySQL"),
    (re.compile(r"(?i)mongodb(\+srv)?://"), "MongoDB"),
    (re.compile(r"(?i)redis://|localhost:6379"), "Redis"),
]


def detect(inv: Inventory, graph_nodes: dict[str, Node], rules_count: int) -> tuple[Architecture, int]:
    # ---- lenguajes ----
    lines_by: Counter = Counter()
    files_by: Counter = Counter()
    total_loc = 0
    for fi in inv.iter_files(tests=True):
        if fi.lang and fi.lang not in ("HTML",):
            n = inv.text(fi).count("\n") + 1 if fi.size else 0
            lines_by[fi.lang] += n
            files_by[fi.lang] += 1
            if fi.lang in CODE_LANGS:
                total_loc += n
    tot = sum(lines_by.values()) or 1
    langs = [LangStat(language=l, files=files_by[l], lines=n, percent=round(n * 100 / tot, 1))
             for l, n in lines_by.most_common(8)]

    # ---- frameworks / datos / mensajería / auth / cloud / pruebas ----
    found: dict[str, set[str]] = defaultdict(set)
    for fi in inv.files:
        if fi.is_generated or fi.ext not in _MANIFEST_EXT and not fi.name.lower().startswith("requirements"):
            continue
        low_name = fi.name.lower()
        if not (low_name.endswith((".csproj", ".vbproj", ".props", ".gradle", ".kts", ".toml", ".cfg")) or low_name in ("package.json", "pom.xml") or low_name.startswith("requirements")):
            continue
        text = inv.text(fi).lower()
        if not text:
            continue
        for key, (label, kind) in _PKG.items():
            if re.search(rf"(?<![\w@/.-]){re.escape(key)}", text):
                found[kind].add(label)
        if low_name.endswith((".csproj",)) and 'sdk="microsoft.net.sdk.web"' in text:
            found["framework"].add("ASP.NET Core")
        if low_name.endswith(".csproj"):
            m = re.search(r"<targetframeworks?>([^<]+)<", text)
            if m:
                found["framework"].add(f".NET ({m.group(1).split(';')[0]})")
    for fi in inv.iter_files(config_=True):
        text = inv.text(fi)
        for rx, label in _CONN_DB:
            if text and rx.search(text):
                found["db"].add(label)

    # ---- contenedores y CI ----
    containers, ci = [], []
    dockerfiles = inv.find(r"(^|/)Dockerfile[^/]*$")
    composes = inv.find(r"(^|/)docker-compose[^/]*\.ya?ml$")
    k8s = [f for f in inv.files if f.ext in (".yaml", ".yml") and re.search(r"(?i)(k8s|kubernetes|helm|charts?|deploy)", f.rel) and "kind:" in inv.text(f)]
    if dockerfiles:
        containers.append(f"Docker ({len(dockerfiles)} Dockerfile)")
    if composes:
        services = 0
        for f in composes:
            services += len(re.findall(r"(?m)^  [\w\-]+:\s*$", inv.text(f).split("services:", 1)[-1])) if "services:" in inv.text(f) else 0
        containers.append(f"Docker Compose ({services or '?'} servicios)")
    if k8s:
        containers.append("Kubernetes / Helm")
    if inv.find(r"(^|/)\.github/workflows/"):
        ci.append("GitHub Actions")
    if inv.find(r"azure-pipelines"):
        ci.append("Azure Pipelines")
    if inv.find(r"\.gitlab-ci\.ya?ml$"):
        ci.append("GitLab CI")
    if inv.find(r"(^|/)Jenkinsfile$"):
        ci.append("Jenkins")
    if inv.find(r"bitbucket-pipelines\.yml$"):
        ci.append("Bitbucket Pipelines")
    if inv.find(r"\.tf$"):
        containers.append("Terraform (IaC)")

    # ---- desplegables ----
    deployables: list[str] = []
    for f in inv.files:
        if f.name.endswith(".csproj") and 'sdk="microsoft.net.sdk.web"' in inv.text(f).lower():
            deployables.append(f.rel.rsplit("/", 1)[0] if "/" in f.rel else f.name)
        elif f.name == "pom.xml" and "spring-boot" in inv.text(f).lower():
            deployables.append(f.rel.rsplit("/", 1)[0] if "/" in f.rel else ".")
        elif f.name == "package.json" and re.search(r'"start"\s*:', inv.text(f)) and "/node_modules/" not in f.rel:
            deployables.append(f.rel.rsplit("/", 1)[0] if "/" in f.rel else ".")
    for f in dockerfiles:
        d = f.rel.rsplit("/", 1)[0] if "/" in f.rel else "."
        if d not in deployables:
            deployables.append(d)
    deployables = list(dict.fromkeys(deployables))[:20]

    # ---- estilo ----
    dirs = inv.dirs
    reasons: list[str] = []
    style = "Aplicación monolítica sin capas claramente separadas"
    has = lambda *names: all(n in dirs for n in names)
    core_like = [n for n in ("domain", "application", "applicationcore", "core", "usecases", "ports") if n in dirs]
    if (has("ports") and has("adapters")) or (len(core_like) >= 2 and "infrastructure" in dirs) or (core_like and "infrastructure" in dirs and ("web" in dirs or "api" in dirs or "publicapi" in dirs)):
        style = "Arquitectura limpia / hexagonal (núcleo de negocio separado de la infraestructura)"
        reasons.append("Carpetas: " + ", ".join(n for n in (*core_like, "infrastructure", "adapters", "web", "api", "publicapi") if n in dirs))
    elif ("controllers" in dirs or "controller" in dirs) and ("services" in dirs or "service" in dirs):
        style = "Arquitectura en capas (controladores → servicios → datos)"
        reasons.append("Carpetas: " + ", ".join(n for n in ("controllers", "services", "repositories", "models", "data") if n in dirs))
    elif any(n.layer in ("controller",) for n in graph_nodes.values()) and any(n.layer == "service" for n in graph_nodes.values()):
        style = "Arquitectura en capas inferida por nombres (controlador → servicio → datos)"
        reasons.append("Clases con sufijos Controller/Service/Repository")
    if len(deployables) >= 3:
        style = "Microservicios / múltiples servicios desplegables" + (f" ({style.split(' (')[0].lower()} dentro de cada uno)" if "capas" in style or "hexagonal" in style else "")
        reasons.append(f"{len(deployables)} componentes desplegables")
    elif len(deployables) == 2:
        reasons.append("2 componentes desplegables (p. ej. backend + frontend)")
    if re.search(r"(?i)mediatr|irequesthandler|icommandhandler", " ".join(found["framework"]) + " ".join(n for n in graph_nodes if n.endswith(("Handler", "Command", "Query")))):
        reasons.append("Patrón CQRS/mediador detectado")
    if found["msg"]:
        reasons.append("Comunicación asíncrona por mensajes: " + ", ".join(sorted(found["msg"])))
    if "microservicios" in style.lower() and not found["msg"]:
        reasons.append("Sin broker de mensajería detectado: la comunicación entre servicios parece síncrona (HTTP).")

    # ---- entidades de dominio (todas las clases declaradas en carpetas de modelo/dominio) ----
    ents: list[str] = []
    skip = re.compile(r"^(Base|Abstract)|(Dto|DTO|Request|Response|ViewModel|Exception|Options|Settings|Config|Attribute|Extensions?|Helper|Utils?|Enum|Context|Validator|Status|Estado|State|Type|Tipo|Result|Details|Data|Specification|Spec|Marker|Info|Aggregate)$")
    for fi in inv.iter_files(code=True, lang={"C#", "Java", "Kotlin", "TypeScript", "Python"}):
        if not re.search(r"(?i)(^|/)(entities|entity|domain|models?)/", fi.rel):
            continue
        for m in re.finditer(r"(?m)^\s*(?:export\s+)?(?:public\s+|internal\s+|abstract\s+|sealed\s+|partial\s+)*class\s+([A-Z]\w*)", inv.text(fi)):
            if not skip.search(m.group(1)):
                ents.append(m.group(1))
    ents = list(dict.fromkeys(ents))[:24]

    # ---- diagrama de contexto ----
    ui = sorted(found["framework"] & {"Angular", "React", "Vue", "Next.js"})
    api = sorted(f for f in found["framework"] if f in ("ASP.NET Core", "FastAPI", "Flask", "Django", "Express", "NestJS", "Spring Boot") or f.startswith(".NET"))
    diagram = ["flowchart LR", '  user(["Usuarios"])']
    prev = "user"
    if ui:
        diagram.append(f'  ui["Interfaz web: {", ".join(ui)}"]'); diagram.append("  user --> ui"); prev = "ui"
    diagram.append(f'  api["Servicio de aplicación{": " + ", ".join(api[:3]) if api else ""}"]')
    diagram.append(f"  {prev} --> api")
    for i, d in enumerate(sorted(found["db"])[:4]):
        diagram.append(f'  db{i}[("{d}")]'); diagram.append(f"  api --> db{i}")
    if found["msg"]:
        diagram.append(f'  mq[["Mensajería: {", ".join(sorted(found["msg"]))}"]]'); diagram.append("  api --> mq")
        diagram.append('  wk["Procesos en segundo plano"]'); diagram.append("  mq --> wk")
    if any("OCR" in e for n in graph_nodes.values() for e in n.externals):
        diagram.append('  ocr["Motor OCR"]'); diagram.append("  api -.-> ocr")
    ext_hosts = sorted({e for n in graph_nodes.values() for e in n.externals if e.startswith("API externa:")})[:4]
    for i, h in enumerate(ext_hosts):
        diagram.append(f'  ex{i}["{h.replace(chr(34), "")}"]'); diagram.append(f"  api -.-> ex{i}")
    if any("Correo" in e for n in graph_nodes.values() for e in n.externals):
        diagram.append('  mail["Correo electrónico"]'); diagram.append("  api -.-> mail")

    return Architecture(
        languages=langs, frameworks=sorted(found["framework"]), style=style, style_reasons=reasons,
        data_stores=sorted(found["db"]), messaging=sorted(found["msg"]), auth=sorted(found["auth"]), cloud=sorted(found["cloud"]),
        containers=containers, ci_cd=ci, deployables=deployables, layers=layer_counts(graph_nodes),
        top_level=inv.top_level, domain_entities=ents, diagram="\n".join(diagram)), total_loc  # type: ignore[return-value]
