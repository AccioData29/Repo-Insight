"""Detección de deuda técnica con urgencia.

Cada detector devuelve hallazgos AGRUPADOS (un hallazgo por tema, con N ocurrencias y evidencia de muestra).
Todo se explica en dos niveles: «por qué importa» (negocio) y detalle técnico + cómo corregirlo.
Los secretos se redactan siempre; el informe nunca contiene credenciales.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..models import DebtFinding, Evidence
from .common import (CODE_LANGS, FileInfo, Inventory, ev, line_of, redact, snippet)

URGENCY = {
    "critical": "Inmediata: atender en los próximos 7 días",
    "high": "Alta: planificar en el siguiente sprint (≤ 30 días)",
    "medium": "Media: incluir en el plan trimestral (≤ 90 días)",
    "low": "Baja: resolver de forma oportunista al tocar el área",
}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Hit:
    fi: FileInfo
    line: int
    text: str


def _finding(category: str, title: str, severity: str, why: str, detail: str, fix: str, hits: list[Hit],
             confidence: str = "alta", extra_evidence: Optional[list[Evidence]] = None) -> DebtFinding:
    seen, evidence = set(), []
    for h in hits:
        if h.fi.rel in seen:
            continue
        seen.add(h.fi.rel)
        evidence.append(ev(h.fi, h.line, h.text))
        if len(evidence) >= 8:
            break
    if extra_evidence:
        evidence = (extra_evidence + evidence)[:8]
    return DebtFinding(
        id="", category=category, title=title, severity=severity, urgency=URGENCY[severity],  # type: ignore[arg-type]
        why_it_matters=why, technical_detail=detail, how_to_fix=fix, occurrences=len(hits) or len(extra_evidence or []),
        files_affected=len({h.fi.rel for h in hits}) or len(extra_evidence or []), evidence=evidence,
        confidence=confidence)  # type: ignore[arg-type]


def _scan(inv: Inventory, rx: re.Pattern, *, code=False, config_=False, tests=False, lang=None,
          skip_line: Optional[Callable[[str], bool]] = None) -> list[Hit]:
    hits: list[Hit] = []
    for fi in inv.iter_files(code=code, config_=config_, tests=tests, lang=lang):
        text = inv.text(fi)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if len(line) > 600:
                continue
            if rx.search(line) and not (skip_line and skip_line(line)):
                hits.append(Hit(fi, i, line))
    return hits


# =============================================================================
# 1. Secretos y conexiones en configuración / código
# =============================================================================
_PLACEHOLDER = re.compile(
    r"^\s*(\$\{.*\}|\{\{.*\}\}|<.*>|#\{.*\}|%.*%|\$\(.*\)|x{3,}|\*+|change[-_ ]?me|your[-_ ].*|<your.*|todo|null|none|"
    r"example.*|secret|password|\{\d+\}|env\..*|process\.env.*|\[.*\])\s*$", re.I)
_CONN_PWD = re.compile(r"(?i)\b(?:password|pwd)\s*=\s*([^;\"'\s]+)")
_CONN_ANY = re.compile(r"(?i)\b(?:server|data source|host|initial catalog|database|user id|uid)\s*=\s*[^;\"']{2,}")
_KV_SECRET = re.compile(
    r"""(?ix)["']?([\w.\-]*(?:password|passwd|pwd|secret|apikey|api_key|accesskey|access_key|privatekey|private_key)[\w.\-]*)["']?\s*[:=]\s*["']?([^"'\s,;}{]{4,})""")
_TOKEN_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "clave de acceso AWS"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"), "token de GitHub"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "token de Slack"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "clave de API de Anthropic"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "clave de API de Google"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "llave privada"),
]
_DEVISH = re.compile(r"(?i)(development|\.dev\b|\.local\b|local|example|sample|template|\.test\b|test|\.dist\b)")
_AMBIG = re.compile(r"(?i)(docker|compose|override|staging|\.qa\b|\.uat\b|sandbox)")


def _is_path_like(val: str) -> bool:
    """Valores como /root/.microsoft/usersecrets:ro o ~/.aspnet/https no son credenciales (montajes de volumen, rutas)."""
    return val.startswith(("/", "~", "./", "../", "$", "%")) or bool(re.match(r"^[A-Za-z]:[\\/]", val))
_ENV_SAMPLE = re.compile(r"(?i)\.(example|sample|template|dist|defaults?)$")


def detect_secrets(inv: Inventory) -> list[DebtFinding]:
    prod_hits: list[Hit] = []
    mid_hits: list[Hit] = []
    dev_hits: list[Hit] = []
    conn_exposed: list[Hit] = []
    conn_dev: list[Hit] = []
    code_hits: list[Hit] = []
    env_files: list[Hit] = []

    for fi in inv.iter_files(config_=True):
        text = inv.text(fi)
        if not text:
            continue
        devish = bool(_DEVISH.search(fi.rel))
        ambig = (not devish) and bool(_AMBIG.search(fi.rel))
        if fi.name.lower().startswith(".env") and not _ENV_SAMPLE.search(fi.name):
            env_files.append(Hit(fi, 1, f"Archivo {fi.name} versionado en el repositorio"))
        for i, line in enumerate(text.splitlines(), 1):
            if len(line) > 800 or line.lstrip().startswith(("#", "//")):
                continue
            tgt = dev_hits if devish else mid_hits if ambig else prod_hits
            m = _CONN_PWD.search(line)
            if m and not _PLACEHOLDER.match(m.group(1)):
                tgt.append(Hit(fi, i, line))
                continue
            km = _KV_SECRET.search(line)
            if km and not _PLACEHOLDER.match(km.group(2)) and not _is_path_like(km.group(2)) \
                    and not re.search(r"(?i)(path|file|url|uri|name|enabled|min|max|length|policy|type|usersecrets)$", km.group(1)):
                tgt.append(Hit(fi, i, line))
                continue
            for rx, _ in _TOKEN_PATTERNS:
                if rx.search(line):
                    tgt.append(Hit(fi, i, line))
                    break
            else:
                if _CONN_ANY.search(line) and not _CONN_PWD.search(line):
                    (conn_dev if devish else conn_exposed).append(Hit(fi, i, line))

    for fi in inv.iter_files(code=True):
        text = inv.text(fi)
        for i, line in enumerate(text.splitlines(), 1):
            if len(line) > 600 or line.lstrip().startswith(("//", "#", "*", "/*")):
                continue
            for rx, _ in _TOKEN_PATTERNS:
                if rx.search(line):
                    code_hits.append(Hit(fi, i, line))
                    break
            else:
                km = re.search(r"""(?i)\b\w*(?:password|passwd|pwd|secret|apikey|api_key|token)\w*\s*=\s*["']([^"']{4,})["']""", line)
                if km and not _PLACEHOLDER.match(km.group(1)) and not re.search(r"(?i)(\s|:|\.|/)", km.group(1)[:1]):
                    code_hits.append(Hit(fi, i, line))
                    continue
                cm = _CONN_PWD.search(line)
                if cm and not _PLACEHOLDER.match(cm.group(1)) and re.search(r"[\"']", line):
                    code_hits.append(Hit(fi, i, line))

    out: list[DebtFinding] = []
    prod_all = prod_hits + code_hits + [h for h in env_files if not _DEVISH.search(h.fi.rel) and not _AMBIG.search(h.fi.rel)]
    if prod_all:
        out.append(_finding(
            "Seguridad", "Credenciales y secretos versionados en el repositorio", "critical",
            "Cualquier persona con acceso al repositorio (o a una copia) puede usar estas contraseñas o llaves para entrar "
            "a bases de datos o servicios reales. Si el repositorio se filtra, también se filtra el acceso al sistema.",
            "Se detectaron contraseñas, cadenas de conexión con contraseña, tokens o llaves privadas en archivos de configuración "
            "y/o código (appsettings*, web.config, .env, properties/yml, código fuente). Los valores se ocultan en este informe. "
            "Aunque se borren hoy, siguen en el historial de git. Si alguno es solo una credencial de demostración, confirme que no se reutiliza en ningún ambiente real.",
            "1) Rotar de inmediato todas las credenciales expuestas. 2) Moverlas a un gestor de secretos (Azure Key Vault, "
            "AWS Secrets Manager, HashiCorp Vault) o a variables de entorno inyectadas por el despliegue. 3) Dejar en el repo solo "
            "plantillas (appsettings.json sin valores, .env.example). 4) Purgar el historial (git filter-repo) y agregar "
            "escaneo de secretos (gitleaks / GitHub secret scanning) al CI.",
            prod_all))
    if mid_hits:
        out.append(_finding(
            "Seguridad", "Credenciales versionadas en archivos de contenedores o ambientes intermedios", "high",
            "Estos archivos suelen empezar como «solo para desarrollo» y terminan copiándose a ambientes compartidos o a producción con la misma contraseña.",
            "Contraseñas o llaves en docker-compose*, appsettings.Docker/Staging u override. Si son estrictamente locales y descartables, el riesgo baja a Medio; "
            "confirme que no se reutilizan en ningún ambiente real.",
            "Leerlas de variables de entorno o de un archivo .env fuera del control de versiones (con .env.example de plantilla) y generar la contraseña local al iniciar.",
            mid_hits, confidence="media"))
    if dev_hits:
        out.append(_finding(
            "Seguridad", "Credenciales de desarrollo/ejemplo versionadas", "medium",
            "Son credenciales de ambientes locales o de ejemplo; el riesgo directo es menor, pero se tiende a reutilizar la misma "
            "contraseña en otros ambientes y normaliza la mala práctica.",
            "Valores de contraseña/secreto en archivos con nombre de desarrollo, ejemplo o prueba.",
            "Usar user-secrets / variables de entorno incluso en local, y dejar solo valores ficticios evidentes en los ejemplos.",
            dev_hits, confidence="media"))
    if conn_exposed:
        out.append(_finding(
            "Configuración", "Cadenas de conexión (servidor, base de datos, usuario) versionadas en archivos de configuración",
            "medium",
            "Aunque no incluyan contraseña, revelan nombres de servidores y bases de datos, y atan el código a un ambiente "
            "concreto: cambiar de servidor exige modificar y volver a publicar el código.",
            "Las conexiones definidas dentro de appsettings*/web.config/properties exponen la topología de infraestructura y "
            "obligan a mantener una copia del archivo por ambiente dentro del repositorio.",
            "Externalizar por ambiente (variables de entorno / Key Vault / Parameter Store), usar identidad administrada o "
            "autenticación integrada cuando la plataforma lo permita, y validar la configuración al arrancar (patrón Options).",
            conn_exposed, confidence="alta"))
    if conn_dev:
        out.append(_finding(
            "Configuración", "Cadenas de conexión de desarrollo versionadas", "low",
            "Bajo riesgo directo, pero consolida la costumbre de configurar infraestructura dentro del código.",
            "Conexiones en archivos de ambiente local/desarrollo.",
            "Mantener solo valores de ejemplo y resolver el resto por entorno.", conn_dev))
    return out


# =============================================================================
# 2. Inyección SQL
# =============================================================================
_SQL = r"(?:select\s.+?\sfrom|insert\s+into|update\s+\S+\s+set|delete\s+from)"
_SQLI = [
    re.compile(rf"""(?i)["'`]\s*{_SQL}[^"'`]*["'`]\s*\+\s*[\w(]"""),
    re.compile(rf"""(?i)\$@?"[^"]*{_SQL}[^"]*\{{[^}}]+\}}"""),
    re.compile(rf"""(?i)string\.Format\(\s*@?"[^"]*{_SQL}"""),
    re.compile(rf"""(?i)execute\w*\(\s*f["'][^"']*{_SQL}[^"']*\{{"""),
    re.compile(rf"""(?i)execute\w*\(\s*["'][^"']*{_SQL}[^"']*["']\s*(?:%|\.format\()"""),
    re.compile(rf"""(?i)(?:createQuery|createNativeQuery|executeQuery|prepareStatement|executeUpdate)\(\s*"[^"]*{_SQL}[^"]*"\s*\+"""),
    re.compile(rf"""(?i)`[^`]*{_SQL}[^`]*\$\{{"""),
]


def detect_sql_injection(inv: Inventory) -> list[DebtFinding]:
    hits: list[Hit] = []
    for fi in inv.iter_files(code=True):
        for i, line in enumerate(inv.lines(fi), 1):
            if len(line) < 600 and any(rx.search(line) for rx in _SQLI):
                hits.append(Hit(fi, i, line))
    if not hits:
        return []
    return [_finding(
        "Seguridad", "Consultas SQL armadas concatenando texto (riesgo de inyección SQL)", "high",
        "Un usuario malintencionado podría leer, modificar o borrar datos escribiendo instrucciones SQL en un campo de la aplicación.",
        "Se construyen sentencias SQL con concatenación o interpolación de variables en vez de parámetros.",
        "Usar consultas parametrizadas (SqlParameter / PreparedStatement / parámetros nombrados) o un ORM; "
        "en EF Core usar FromSql con interpolación segura; validar listas blancas para nombres de columnas/orden.",
        hits, confidence="media")]


# =============================================================================
# 3. OCR
# =============================================================================
_OCR_REF = re.compile(
    r"(?i:tesseract|pytesseract|easyocr|paddleocr|tess4j|ocrmypdf|ironocr|aspose\.ocr|computervision|readinstream|"
    r"analyzedocument|documentintelligence|formrecognizer|textract|documenttextdetection|imageannotator|"
    r"windows\.media\.ocr|ocrengine)|(?<![A-Za-z])(?:OCR|Ocr|ocr)(?![a-z])")
_OCR_CONF = re.compile(r"(?i)confidence|\bconf\b|\bscore\b|threshold|umbral|probab")
_OCR_RESIL = re.compile(r"(?i)timeout|CancellationToken|retry|polly|tenacity|backoff|max_retries")
_OCR_ASYNC = re.compile(r"(?i)queue|background|hangfire|celery|enqueue|publish|worker|task\.run|bullmq|\.delay\(|apply_async")
_OCR_PRE = re.compile(r"(?i)deskew|binar|gr[ae]yscale|denoise|threshold|resize|opencv|cv2|imagesharp|magick|pillow|\bPIL\b|\bdpi\b|contrast")
_REGEX_USE = re.compile(r"Regex[\.(]|\bre\.(?:search|match|findall|compile|sub)\(|new RegExp|Pattern\.compile|\.match\(/")
_HTTP_ROUTE = re.compile(r"(?i)\[Http(?:Get|Post|Put|Delete)|@(?:Get|Post|Put|Delete)Mapping|@(?:app|router)\.(?:get|post|put|route)|\.MapPost\(|app\.post\(|router\.post\(|IFormFile|request\.files")


def detect_ocr(inv: Inventory) -> list[DebtFinding]:
    code_files: list[tuple[FileInfo, int, str]] = []
    manifests: list[Hit] = []
    for fi in inv.iter_files():
        if fi.is_code:
            text = inv.text(fi)
            if not text:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if len(line) < 600 and _OCR_REF.search(line) and not line.lstrip().startswith(("//", "#", "*")):
                    code_files.append((fi, i, line))
                    break
        elif fi.ext in (".csproj", ".txt", ".json", ".xml", ".gradle", ".toml") or fi.name.lower() in ("requirements.txt", "pom.xml"):
            for i, line in enumerate(inv.lines(fi), 1):
                if len(line) < 400 and re.search(r"(?i)tesseract|easyocr|paddleocr|tess4j|ocrmypdf|ironocr|aspose\.ocr|computervision|formrecognizer|documentintelligence|textract", line):
                    manifests.append(Hit(fi, i, line))
                    break
    trained = [f for f in inv.files if f.ext == ".traineddata"]
    if not code_files and not manifests:
        return []

    ocr_fis = {fi.rel: fi for fi, _, _ in code_files}
    texts = {rel: inv.text(fi) for rel, fi in ocr_fis.items()}
    issues: list[str] = []
    in_request = [r for r, t in texts.items() if _HTTP_ROUTE.search(t) or re.search(r"(?i)(^|/)(controllers?|routes?|views|api)/", r)]
    sync_files = [r for r, t in texts.items() if not _OCR_ASYNC.search(t)]
    if in_request:
        issues.append("El OCR se ejecuta dentro de la misma petición HTTP que recibe el archivo (bloquea al usuario y se cae por timeouts con documentos grandes).")
    elif sync_files:
        issues.append("No se observa desacople asíncrono (cola/worker) alrededor del OCR: se procesa en línea.")
    if texts and not any(_OCR_CONF.search(t) for t in texts.values()):
        issues.append("No se evalúa la confianza/score del OCR: texto mal leído entra al sistema como si fuera correcto.")
    if texts and not any(_OCR_RESIL.search(t) for t in texts.values()):
        issues.append("Sin timeouts, reintentos ni cancelación alrededor del OCR (un documento problemático puede dejar procesos colgados).")
    regex_files = [r for r, t in texts.items() if _REGEX_USE.search(t)]
    if regex_files:
        issues.append("El texto del OCR se interpreta con expresiones regulares: es frágil ante variaciones de formato, ruido y errores de lectura.")
    if texts and not any(_OCR_PRE.search(t) for t in texts.values()):
        issues.append("No hay preprocesamiento de imagen (enderezar, binarizar, escalar a ≥300 DPI) antes del OCR, lo que reduce la precisión.")
    if trained:
        issues.append(f"Modelos de idioma ({len(trained)} archivo(s) .traineddata) versionados en el repositorio: inflan el repo y fijan versiones.")

    serious = sum(1 for s in issues if not s.startswith(("No hay preprocesamiento", "Modelos de idioma")))
    sev = "high" if serious >= 3 else "medium" if serious >= 1 else "low"
    if not issues:
        return []
    hits = [Hit(fi, ln, line) for fi, ln, line in code_files] + manifests
    return [_finding(
        "Procesamiento de documentos (OCR)", "Manejo deficiente del OCR", sev,
        "Los documentos leídos con errores pueden generar datos incorrectos (montos, fechas, identificaciones) sin que nadie lo note, "
        "y un OCR síncrono puede hacer lenta o inestable la aplicación para todos los usuarios.",
        "Problemas detectados:\n- " + "\n- ".join(issues),
        "Desacoplar con cola + worker (carga → cola → OCR → resultado); guardar el resultado crudo y la confianza por campo; "
        "definir umbral de confianza y enviar a revisión humana lo dudoso; preprocesar la imagen; aplicar timeouts/reintentos "
        "idempotentes; y validar los campos extraídos contra reglas de negocio (formato, rangos, dígitos de control) antes de aceptarlos.",
        hits, confidence="media")]


# =============================================================================
# 4. Procesos encolados / en segundo plano
# =============================================================================
_QUEUE_TECH = {
    "RabbitMQ": r"RabbitMQ\.Client|\bpika\b|amqplib|@RabbitListener|spring-rabbit",
    "Kafka": r"Confluent\.Kafka|kafka-python|confluent_kafka|kafkajs|@KafkaListener|spring-kafka",
    "MassTransit": r"\bMassTransit\b",
    "NServiceBus": r"NServiceBus",
    "Azure Service Bus": r"ServiceBusClient|Azure\.Messaging\.ServiceBus|azure-servicebus|ServiceBusTrigger",
    "AWS SQS": r"AmazonSQS|@aws-sdk/client-sqs|\bSQS\b|sqs\.(?:send|receive)",
    "Hangfire": r"\bHangfire\b|BackgroundJob\.Enqueue|RecurringJob\.",
    "Quartz": r"\bQuartz\b",
    "Celery": r"\bcelery\b|@shared_task|\.delay\(|apply_async",
    "BullMQ/Bull": r"\bbullmq?\b",
    "Azure Functions (cola/timer)": r"QueueTrigger|TimerTrigger|\[FunctionName",
    "Tareas programadas Spring": r"@Async|@Scheduled",
    "BackgroundService / IHostedService": r"BackgroundService|IHostedService",
}
_INMEM = re.compile(r"Channel\.Create(?:Un)?[Bb]ounded|ConcurrentQueue<|BlockingCollection<|asyncio\.Queue\(|\bqueue\.Queue\(")
_FIRE = re.compile(r"\bTask\.Run\(|_\s*=\s*Task\.|threading\.Thread\(|new Thread\(|ThreadPool\.QueueUserWorkItem")
_GOV = {
    "cola de mensajes fallidos (DLQ)": re.compile(r"(?i)dead.?letter|\bDLQ\b|poison"),
    "reintentos con espera": re.compile(r"(?i)retry|polly|backoff|tenacity|max_retries|AutomaticRetry"),
    "idempotencia / deduplicación": re.compile(r"(?i)idempot|dedup|MessageId|correlation"),
    "patrón Outbox": re.compile(r"(?i)\boutbox\b"),
    "observabilidad (métricas/trazas/health)": re.compile(r"(?i)opentelemetry|activitysource|prometheus|healthcheck|health_check|actuator"),
}


def detect_queues(inv: Inventory) -> list[DebtFinding]:
    tech_hits: dict[str, list[Hit]] = {k: [] for k in _QUEUE_TECH}
    inmem: list[Hit] = []
    fire: list[Hit] = []
    rxs = {k: re.compile(v) for k, v in _QUEUE_TECH.items()}
    all_text_for_gov = []
    for fi in inv.iter_files():
        if not (fi.is_code or fi.ext in (".csproj", ".txt", ".json", ".xml", ".gradle", ".toml", ".yml", ".yaml")):
            continue
        text = inv.text(fi)
        if not text:
            continue
        all_text_for_gov.append(text)
        for i, line in enumerate(text.splitlines(), 1):
            if len(line) > 500 or line.lstrip().startswith(("//", "#", "*")):
                continue
            for k, rx in rxs.items():
                if len(tech_hits[k]) < 40 and rx.search(line):
                    tech_hits[k].append(Hit(fi, i, line))
            if fi.is_code:
                if _INMEM.search(line):
                    inmem.append(Hit(fi, i, line))
                elif _FIRE.search(line):
                    fire.append(Hit(fi, i, line))
    found = {k: v for k, v in tech_hits.items() if v}
    out: list[DebtFinding] = []
    if inmem or fire:
        out.append(_finding(
            "Procesos asíncronos", "Colas en memoria y tareas «dispara y olvida» (se pierden al reiniciar)", "high",
            "Si el servidor se reinicia o se despliega una versión nueva mientras hay trabajo pendiente, ese trabajo desaparece sin dejar rastro: "
            "pedidos sin procesar, correos no enviados, documentos sin leer.",
            "Se usan estructuras en memoria (Channel, ConcurrentQueue, BlockingCollection, queue.Queue, asyncio.Queue) o tareas lanzadas sin "
            "seguimiento (Task.Run sin await, hilos manuales) para trabajo que debería ser durable.",
            "Usar un broker o almacén durable (RabbitMQ, Azure Service Bus, SQS, Kafka según volumen; o Hangfire/Quartz con almacenamiento persistente), "
            "con reintentos, DLQ e idempotencia. Para escritura + publicación atómica usar el patrón Outbox.",
            inmem + fire, confidence="media"))
    if found:
        blob = "\n".join(all_text_for_gov)
        present = [n for n, rx in _GOV.items() if rx.search(blob)]
        missing = [n for n, rx in _GOV.items() if not rx.search(blob)]
        crit_missing = [m for m in missing if m.startswith(("cola de mensajes fallidos", "reintentos", "idempotencia"))]
        sev = "high" if len(crit_missing) >= 2 else "medium"
        techs = ", ".join(f"{k} ({len(v)} refs)" for k, v in found.items())
        first_hits = [h for v in found.values() for h in v[:3]]
        out.append(_finding(
            "Procesos asíncronos", "Procesos encolados o programados sin gobierno visible", sev,
            "El trabajo en segundo plano falla en silencio: nadie ve que algo quedó atascado, se procesa dos veces o se pierde. "
            "Hace que los incidentes se descubran por reclamos del cliente.",
            f"Tecnologías detectadas: {techs}.\n"
            f"Controles presentes: {', '.join(present) or 'ninguno detectado'}.\n"
            f"Controles NO detectados en el código: {', '.join(missing) or 'ninguno'}.",
            "Para cada cola/job definir: reintentos con espera exponencial, DLQ con alerta, idempotencia (clave de deduplicación), "
            "límite de concurrencia, métricas (profundidad de cola, edad del mensaje más antiguo) y un panel de operación con acceso restringido. "
            "Si el flujo es de pasos largos con compensaciones, evaluar un orquestador de workflows (Temporal / Durable Functions).",
            first_hits, confidence="media"))
    return out


# =============================================================================
# 5. Otros patrones de código
# =============================================================================
def detect_async_misuse(inv: Inventory) -> list[DebtFinding]:
    rx = re.compile(r"\.GetAwaiter\(\)\.GetResult\(\)|\.Wait\(\)|\)\.Result\b|Task\.WaitAll\(|async\s+void\s+(?!\w+\(\s*object\s+sender)")
    hits = _scan(inv, rx, code=True, lang={"C#"}, skip_line=lambda l: l.lstrip().startswith("//"))
    if not hits:
        return []
    return [_finding(
        "Rendimiento y estabilidad", "Código asíncrono bloqueado con .Result / .Wait() / async void", "medium",
        "Puede congelar la aplicación bajo carga (se agotan los hilos) y ocultar errores que nadie ve.",
        "Bloqueo sincrónico de tareas asíncronas y métodos async void fuera de manejadores de eventos.",
        "Propagar async/await hasta el punto de entrada, usar Task en lugar de async void y pasar CancellationToken.", hits, "media")]


def detect_swallowed_exceptions(inv: Inventory) -> list[DebtFinding]:
    pats = [
        re.compile(r"catch\s*(?:\([^)]*\))?\s*\{\s*(?://[^\n]*)?\s*\}"),
        re.compile(r"except[^\n:]*:[ \t]*\n[ \t]+(?:pass|\.\.\.)[ \t]*(?:#[^\n]*)?(?:\n|$)"),
    ]
    hits: list[Hit] = []
    for fi in inv.iter_files(code=True):
        text = inv.text(fi)
        if not text:
            continue
        for rx in pats:
            for m in rx.finditer(text):
                ln = line_of(text, m.start())
                hits.append(Hit(fi, ln, text.splitlines()[ln - 1] if ln - 1 < len(text.splitlines()) else m.group(0)))
    if not hits:
        return []
    sev = "high" if len(hits) >= 15 else "medium"
    return [_finding(
        "Calidad", "Errores silenciados (catch/except vacíos)", sev,
        "Los fallos desaparecen sin aviso: la operación parece exitosa pero no se hizo, y luego es casi imposible investigar qué pasó.",
        "Bloques catch/except que no registran, no relanzan ni comunican el error.",
        "Capturar solo excepciones específicas, registrar con contexto (logging estructurado) y decidir explícitamente: reintentar, compensar o propagar.",
        hits)]


def detect_insecure_tls(inv: Inventory) -> list[DebtFinding]:
    rx = re.compile(r"ServerCertificateCustomValidationCallback\s*=.*(?:true|=>\s*true)|ServerCertificateValidationCallback\s*[+=].*true|"
                    r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|"
                    r"InsecureSkipVerify\s*:\s*true|TrustAllCerts|ALLOW_ALL_HOSTNAME_VERIFIER|DangerousAcceptAnyServerCertificateValidator")
    hits = _scan(inv, rx, code=True) + _scan(inv, rx, config_=True)
    if not hits:
        return []
    return [_finding(
        "Seguridad", "Validación de certificados TLS desactivada", "high",
        "Las comunicaciones «seguras» dejan de serlo: un atacante en la red puede interceptar o alterar datos sensibles sin ser detectado.",
        "Se acepta cualquier certificado en llamadas HTTPS.",
        "Eliminar el bypass; instalar la CA corporativa en el almacén de confianza del contenedor/servidor o fijar el certificado esperado.", hits)]


def detect_cors(inv: Inventory) -> list[DebtFinding]:
    rx = re.compile(r"AllowAnyOrigin\(\)|allow_origins\s*=\s*\[\s*[\"']\*|origin\s*:\s*[\"']\*[\"']|@CrossOrigin\s*(?:\(\s*\))?\s*$|"
                    r"setAllowedOrigins\(.*\*|Access-Control-Allow-Origin[\"']?\s*[:,]\s*[\"']\*")
    hits = _scan(inv, rx, code=True) + _scan(inv, rx, config_=True)
    if not hits:
        return []
    return [_finding(
        "Seguridad", "CORS abierto a cualquier origen", "medium",
        "Cualquier sitio web puede invocar la API desde el navegador de un usuario autenticado.",
        "Política CORS con comodín (*) o sin restricción.",
        "Listar explícitamente los orígenes permitidos por ambiente.", hits)]


def detect_sensitive_logging(inv: Inventory) -> list[DebtFinding]:
    rx = re.compile(r"(?i)(?:log\w*|logger\.\w+|console\.(?:log|error|warn)|print|Console\.Write(?:Line)?)\s*\(.*(?:\{[^}]*(?:password|token|secret|authorization)[^}]*\}|\+\s*\w*(?:password|token|secret)\w*|,\s*\w*(?:password|token|secret)\w*\s*[,)])")
    hits = _scan(inv, rx, code=True)
    if not hits:
        return []
    return [_finding(
        "Seguridad", "Posible registro de contraseñas o tokens en los logs", "medium",
        "Los logs suelen tener un acceso más amplio que la base de datos; quien los lea podría obtener credenciales de usuarios.",
        "Instrucciones de log que incluyen variables con nombre password/token/secret.",
        "Nunca registrar credenciales; enmascarar datos sensibles en el formateador de logs.", hits, "baja")]


def detect_hardcoded_environment(inv: Inventory) -> list[DebtFinding]:
    ip = re.compile(r"(?<![\w.\-])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.\-])")
    winpath = re.compile(r"""["'][A-Za-z]:\\{1,2}[\w\\ .\-]{3,}""")
    http = re.compile(r"""["']http://(?!localhost|127\.|0\.0\.0\.0|schemas\.|www\.w3\.org|java\.sun|xmlns|maven|host\.docker\.internal|[\w\-]+[/:"'])[\w\-]+(?:\.[\w\-]+)+""")
    hits: list[Hit] = []
    for fi in list(inv.iter_files(code=True)) + list(inv.iter_files(config_=True)):
        for i, line in enumerate(inv.lines(fi), 1):
            if len(line) > 400 or line.lstrip().startswith(("//", "#", "*", "<!--")):
                continue
            if re.search(r"(?i)version|assembly|xmlns|include=|publickeytoken|culture=", line):
                continue
            m = ip.search(line)
            if m and not m.group(0).startswith(("127.", "0.", "255.")):
                hits.append(Hit(fi, i, line))
                continue
            if winpath.search(line) or http.search(line):
                hits.append(Hit(fi, i, line))
    if not hits:
        return []
    sev = "medium" if len(hits) >= 3 else "low"
    return [_finding(
        "Configuración", "Direcciones IP, rutas del servidor y URLs fijas en código o configuración", sev,
        "El sistema solo funciona en el servidor para el que fue escrito; mover, escalar o recuperar el sistema ante una falla se vuelve lento y riesgoso.",
        "IPs literales, rutas absolutas de Windows (C:\\...) o URLs http:// sin cifrar escritas directamente.",
        "Parametrizar por ambiente, usar nombres DNS/servicios descubribles, almacenamiento de objetos o rutas relativas configurables, y HTTPS.",
        hits, "media")]


def detect_authentication(inv: Inventory) -> list[DebtFinding]:
    cs_ctrl = [f for f in inv.iter_files(code=True, lang={"C#"}) if re.search(r"Controller\.cs$", f.rel)]
    java_ctrl = [f for f in inv.iter_files(code=True, lang={"Java", "Kotlin"}) if "@RestController" in inv.text(f) or "@Controller" in inv.text(f)]
    out: list[DebtFinding] = []
    if cs_ctrl:
        auth = re.compile(r"\[Authorize|AddAuthentication|AddJwtBearer|RequireAuthorization|UseAuthentication|AuthorizeFilter|IdentityServer|AddMicrosoftIdentityWebApi|AddOpenIdConnect")
        if not inv.corpus_has(auth):
            hits = [Hit(f, 1, f"Controlador {f.name} sin atributos de autorización") for f in cs_ctrl]
            out.append(_finding(
                "Seguridad", "API sin autenticación/autorización aparente", "high",
                "Si estos servicios están expuestos, cualquiera podría consultarlos o ejecutarlos sin identificarse.",
                f"{len(cs_ctrl)} controlador(es) y ninguna referencia a [Authorize], AddAuthentication, JwtBearer, etc. "
                "Puede estar resuelto por un gateway externo (no verificable desde el código).",
                "Habilitar autenticación (OIDC/JWT) y una política de autorización por defecto; marcar excepciones con [AllowAnonymous].", hits, "media"))
    if java_ctrl:
        sec = re.compile(r"spring-boot-starter-security|@PreAuthorize|SecurityFilterChain|WebSecurityConfigurer|@Secured|@RolesAllowed")
        if not inv.corpus_has(sec):
            hits = [Hit(f, 1, f"Controlador {f.name} sin seguridad configurada") for f in java_ctrl]
            out.append(_finding(
                "Seguridad", "API sin Spring Security / autorización aparente", "high",
                "Si estos servicios están expuestos, cualquiera podría usarlos sin identificarse.",
                f"{len(java_ctrl)} controlador(es) y ninguna referencia a Spring Security. Puede resolverlo un gateway (no verificable aquí).",
                "Agregar Spring Security con OAuth2/JWT y reglas por ruta/rol.", hits, "media"))
    return out


_EOL_NOTE = "Verifique las fechas vigentes en la política oficial del fabricante."


def detect_outdated_stack(inv: Inventory) -> list[DebtFinding]:
    items: dict[str, list[tuple[str, Hit]]] = {}

    def add(tech: str, sev: str, hit: Hit) -> None:
        items.setdefault(tech, []).append((sev, hit))

    for fi in inv.iter_files(ext=(".csproj", ".props", ".vbproj")):
        for i, line in enumerate(inv.lines(fi), 1):
            m = re.search(r"<TargetFramework(?:s)?>([^<]+)<", line)
            if m:
                for tfm in m.group(1).split(";"):
                    tfm = tfm.strip().lower()
                    if re.match(r"^net(40|45|451|452|46|461)$", tfm) or re.match(r"^netcoreapp[123]\.\d$", tfm) or re.match(r"^net[567]\.0$", tfm):
                        add(f".NET ({tfm})", "high", Hit(fi, i, line))
                    elif re.match(r"^net(462|47|471|472|48|481)$", tfm):
                        add(f".NET Framework ({tfm})", "medium", Hit(fi, i, line))
                    elif tfm in ("net8.0", "net9.0"):
                        add(f".NET ({tfm}) — soporte termina en noviembre de 2026", "medium", Hit(fi, i, line))
            m = re.search(r"<TargetFrameworkVersion>v(\d+\.\d+)", line)
            if m:
                add(f".NET Framework {m.group(1)}", "high" if float(m.group(1)) < 4.6 else "medium", Hit(fi, i, line))
    for fi in inv.iter_files(config_=False, ext=(".json",), name_re=re.compile(r"(^|/)package\.json$")):
        text = inv.text(fi)
        try:
            data = json.loads(text)
        except Exception:
            continue
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        def lineno(key: str) -> int:
            for i, l in enumerate(text.splitlines(), 1):
                if f'"{key}"' in l:
                    return i
            return 1
        ng = deps.get("@angular/core")
        if ng:
            m = re.search(r"(\d+)", ng)
            if m and int(m.group(1)) <= 18:
                add(f"Angular {m.group(1)}", "high" if int(m.group(1)) <= 15 else "medium", Hit(fi, lineno("@angular/core"), f'"@angular/core": "{ng}"'))
        if str(deps.get("angular", "")).startswith(("1.", "~1.", "^1.")):
            add("AngularJS 1.x", "high", Hit(fi, lineno("angular"), f'"angular": "{deps["angular"]}"'))
        node = data.get("engines", {}).get("node", "")
        m = re.search(r"(\d+)", node)
        if m and int(m.group(1)) <= 20:
            add(f"Node.js {m.group(1)}", "high" if int(m.group(1)) <= 18 else "medium", Hit(fi, lineno("node"), f'"node": "{node}"'))
    for fi in inv.iter_files(name_re=re.compile(r"(?i)(^|/)(Dockerfile[^/]*|\.nvmrc|runtime\.txt|\.python-version|\.tool-versions)$")):
        for i, line in enumerate(inv.lines(fi), 1):
            m = re.search(r"(?i)FROM\s+(?:[\w./\-]+/)?(node|python|openjdk|eclipse-temurin|maven)[:@]?(\d+)(?:\.(\d+))?", line)
            if m:
                tech, major, minor = m.group(1).lower(), int(m.group(2)), int(m.group(3) or 0)
                if tech == "node" and major <= 20:
                    add(f"Node.js {major}", "high" if major <= 18 else "medium", Hit(fi, i, line))
                elif tech == "python" and (major == 2 or (major == 3 and minor <= 10)):
                    add(f"Python {major}.{minor}", "high" if major == 2 or minor <= 9 else "medium", Hit(fi, i, line))
                elif tech in ("openjdk", "eclipse-temurin") and major <= 11:
                    add(f"Java {major}", "high" if major <= 8 else "medium", Hit(fi, i, line))
    for fi in inv.iter_files(name_re=re.compile(r"(?i)(^|/)(pom\.xml|build\.gradle(\.kts)?)$")):
        for i, line in enumerate(inv.lines(fi), 1):
            m = re.search(r"<(?:java\.version|maven\.compiler\.(?:source|target|release))>(?:1\.)?(\d+)<|(?:sourceCompatibility|JavaVersion\.VERSION_)\s*=?\s*['\"]?(?:1[._])?(\d+)", line)
            if m:
                v = int(m.group(1) or m.group(2))
                if v <= 11:
                    add(f"Java {v}", "high" if v <= 8 else "medium", Hit(fi, i, line))
    for fi in inv.iter_files(code=True, lang={"Python"}):
        for i, line in enumerate(inv.lines(fi), 1):
            if re.match(r"^\s*print\s+[\"']", line):
                add("Python 2 (sentencias print)", "high", Hit(fi, i, line))
                break

    out: list[DebtFinding] = []
    for tech, lst in items.items():
        sev = min((s for s, _ in lst), key=lambda s: SEV_ORDER[s])
        out.append(_finding(
            "Plataforma y versiones", f"Tecnología desactualizada o fuera de soporte: {tech}", sev,
            "Las versiones sin soporte dejan de recibir parches de seguridad; además, cada año que pasa encarece y complica la actualización "
            "y reduce la cantidad de personas que pueden mantener el sistema.",
            f"Versión detectada: {tech}. {_EOL_NOTE}",
            "Planificar la actualización por etapas (primero dependencias y pruebas, luego framework), usando asistentes de migración del fabricante "
            "(p. ej. .NET Upgrade Assistant, ng update, 2to3) y cubriendo antes las reglas críticas con pruebas.",
            [h for _, h in lst], "alta"))
    return out


def detect_tests(inv: Inventory) -> list[DebtFinding]:
    src = [f for f in inv.iter_files(code=True, tests=False) if not f.is_test]
    tests = [f for f in inv.files if f.is_test and f.is_code]
    n_src, n_tests = len(src), len(tests)
    if n_src < 15:
        return []
    ratio = n_tests / max(n_src, 1)
    if n_tests == 0:
        return [_finding("Calidad", "Sin pruebas automatizadas", "high",
                         "Cada cambio puede romper una regla de negocio sin que nadie lo note hasta que falla en producción; los cambios se vuelven lentos y temidos.",
                         f"{n_src} archivos de código y ninguna prueba detectada.",
                         "Empezar por pruebas de caracterización de las reglas críticas (este informe sirve de backlog), luego pruebas de integración de los flujos principales.",
                         [], "alta", [Evidence(file="(repositorio)", line=0, snippet=f"{n_src} archivos de código, 0 de pruebas")])]
    if ratio < 0.05:
        return [_finding("Calidad", "Cobertura de pruebas muy baja (por cantidad de archivos)", "medium",
                         "La mayor parte del comportamiento no está protegida frente a cambios.",
                         f"{n_tests} archivos de prueba frente a {n_src} de código ({ratio:.0%}). No mide cobertura real de líneas.",
                         "Medir cobertura en CI y fijar un umbral progresivo, priorizando reglas de negocio y flujos críticos.",
                         [], "media", [Evidence(file="(repositorio)", line=0, snippet=f"{n_tests} pruebas / {n_src} archivos de código")])]
    return []


def detect_ci(inv: Inventory) -> list[DebtFinding]:
    if len(inv.files) < 20:
        return []
    ci = inv.find(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|azure-pipelines[^/]*\.ya?ml|\.gitlab-ci\.ya?ml|Jenkinsfile|bitbucket-pipelines\.yml|\.circleci/config\.yml|\.drone\.yml|buildspec\.ya?ml)$")
    if ci:
        return []
    return [_finding("Entrega continua", "Sin integración/entrega continua (CI/CD) en el repositorio", "medium",
                     "Las publicaciones dependen de pasos manuales: más errores humanos, despliegues lentos y sin garantía de que lo publicado coincida con lo revisado.",
                     "No hay definiciones de pipelines (GitHub Actions, Azure Pipelines, GitLab CI, Jenkins, Bitbucket Pipelines). Puede existir fuera del repo.",
                     "Definir pipeline mínimo: compilar → pruebas → análisis de seguridad (CodeQL/SAST, dependencias, secretos) → artefacto → despliegue por ambiente con aprobación.",
                     [], "media", [Evidence(file="(repositorio)", line=0, snippet="No se encontraron archivos de pipeline")])]


def detect_god_files(inv: Inventory) -> list[DebtFinding]:
    hits = []
    for fi in inv.iter_files(code=True):
        n = len(inv.lines(fi))
        if n > 1000:
            hits.append((n, Hit(fi, 1, f"{n} líneas")))
    if not hits:
        return []
    hits.sort(key=lambda x: -x[0])
    sev = "medium" if hits[0][0] > 2000 or len(hits) >= 5 else "low"
    return [_finding("Mantenibilidad", f"Archivos gigantes ({len(hits)} con más de 1.000 líneas)", sev,
                     "Los archivos enormes mezclan responsabilidades; cambiar una regla obliga a tocar código ajeno y aumenta el riesgo de errores.",
                     "Mayores: " + ", ".join(f"{h.fi.rel} ({n})" for n, h in hits[:5]),
                     "Dividir por responsabilidad (reglas de dominio, acceso a datos, orquestación) empezando por los archivos que más cambian.",
                     [h for _, h in hits])]


def detect_todos(inv: Inventory) -> list[DebtFinding]:
    hits = _scan(inv, re.compile(r"(?://|#|/\*|<!--)\s*(?:TODO|FIXME|HACK|XXX)\b"), code=True)
    if len(hits) < 5:
        return []
    return [_finding("Mantenibilidad", f"{len(hits)} marcas TODO/FIXME/HACK sin resolver", "medium" if len(hits) > 50 else "low",
                     "Son atajos y pendientes reconocidos por el propio equipo; algunos pueden ser reglas de negocio incompletas.",
                     "Comentarios TODO/FIXME/HACK/XXX en el código.",
                     "Convertirlos en tickets priorizados o eliminarlos; revisar primero los que mencionan validaciones o seguridad.", hits)]


def detect_dependency_hygiene(inv: Inventory) -> list[DebtFinding]:
    hits: list[Hit] = []
    for fi in inv.iter_files(name_re=re.compile(r"(^|/)package\.json$")):
        for i, line in enumerate(inv.lines(fi), 1):
            if re.search(r'":\s*"(\*|latest)"', line):
                hits.append(Hit(fi, i, line))
    for fi in inv.iter_files(ext=(".csproj",)):
        for i, line in enumerate(inv.lines(fi), 1):
            if re.search(r'Version="(\*|\[\*|[\d.]+\.\*)', line):
                hits.append(Hit(fi, i, line))
    for fi in inv.iter_files(name_re=re.compile(r"(^|/)requirements[^/]*\.txt$")):
        for i, line in enumerate(inv.lines(fi), 1):
            s = line.strip()
            if s and not s.startswith(("#", "-", "git+", "http")) and not re.search(r"==|@|~=|>=.*,<", s):
                hits.append(Hit(fi, i, line))
    pkg = inv.find(r"(^|/)package\.json$")
    lock = inv.find(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$")
    extra = []
    if pkg and not lock:
        extra.append(Evidence(file=pkg[0].rel, line=1, snippet="package.json sin archivo de bloqueo (lockfile)"))
    if not hits and not extra:
        return []
    return [_finding("Dependencias", "Versiones de dependencias sin fijar", "medium" if any("latest" in h.text or '"*"' in h.text for h in hits) else "low",
                     "Dos compilaciones del mismo código pueden traer librerías distintas: errores que «solo pasan en producción» y riesgo de incorporar versiones vulnerables sin saberlo.",
                     "Uso de *, latest o dependencias sin versión exacta / sin lockfile.",
                     "Fijar versiones (lockfiles), automatizar actualizaciones con Dependabot/Renovate y escanear vulnerabilidades en CI.", hits, "alta", extra)]


def detect_committed_artifacts(inv: Inventory) -> list[DebtFinding]:
    binex = [f for f in inv.files if f.ext in (".dll", ".exe", ".jar", ".zip", ".rar", ".7z", ".pdb") and not f.is_generated]
    if not inv.artifacts and len(binex) < 3:
        return []
    extra = [Evidence(file=k + "/", line=0, snippet=f"{v} carpeta(s) versionada(s)") for k, v in inv.artifacts.items()]
    hits = [Hit(f, 1, f"{f.size // 1024} KB") for f in binex[:30]]
    sev = "medium" if inv.artifacts else "low"
    return [_finding("Mantenibilidad", "Binarios, dependencias o compilados versionados en el repositorio", sev,
                     "Infla el repositorio, vuelve lentos los clones y puede esconder código desactualizado o con vulnerabilidades que nadie revisa.",
                     "Carpetas node_modules/obj/bin o archivos .dll/.exe/.jar/.zip dentro del control de versiones.",
                     "Agregar .gitignore adecuado, retirar los artefactos del repo y usar un registro de paquetes (NuGet/npm/Maven) o almacenamiento de artefactos.",
                     hits, "alta", extra)]


def detect_observability(inv: Inventory) -> list[DebtFinding]:
    if len([f for f in inv.iter_files(code=True)]) < 25:
        return []
    rx = re.compile(r"Serilog|NLog|log4net|ILogger<|Microsoft\.Extensions\.Logging|log4j|slf4j|logback|logging\.getLogger|structlog|loguru|winston|pino|bunyan|OpenTelemetry|Sentry|Application ?Insights")
    if inv.corpus_has(rx):
        return []
    return [_finding("Operación", "Sin logging estructurado ni telemetría aparente", "medium",
                     "Cuando algo falla en producción no hay forma fiable de saber qué ocurrió, a quién afectó ni desde cuándo.",
                     "No se encontraron librerías de logging estructurado, métricas ni trazas.",
                     "Adoptar logging estructurado con correlación por petición y OpenTelemetry (trazas + métricas) con alertas sobre errores y latencia.",
                     [], "media", [Evidence(file="(repositorio)", line=0, snippet="Sin referencias a Serilog/NLog/log4j/logging/OpenTelemetry…")])]


DETECTORS = [
    detect_secrets, detect_sql_injection, detect_ocr, detect_queues, detect_authentication, detect_insecure_tls,
    detect_cors, detect_sensitive_logging, detect_async_misuse, detect_swallowed_exceptions, detect_outdated_stack,
    detect_hardcoded_environment, detect_tests, detect_ci, detect_dependency_hygiene, detect_committed_artifacts,
    detect_observability, detect_god_files, detect_todos,
]


def run_all(inv: Inventory, progress: Optional[Callable[[str], None]] = None) -> list[DebtFinding]:
    findings: list[DebtFinding] = []
    for det in DETECTORS:
        try:
            findings.extend(det(inv))
        except Exception as exc:  # un detector defectuoso no debe tumbar el análisis
            findings.append(DebtFinding(
                id="", category="Herramienta", title=f"El detector «{det.__name__}» falló", severity="low",
                urgency=URGENCY["low"], why_it_matters="Este análisis quedó incompleto.", technical_detail=redact(str(exc))[:200],
                how_to_fix="Reportar el caso al equipo de la herramienta.", occurrences=0, files_affected=0, evidence=[], confidence="baja"))
        if progress:
            progress(det.__name__)
    findings.sort(key=lambda f: (SEV_ORDER[f.severity], -f.occurrences))
    for i, f in enumerate(findings, 1):
        f.id = f"DT-{i:02d}"
    return findings
