"""Recomendaciones de arquitectura y tecnología, SIEMPRE con evidencia, justificación, costo/beneficio y cuándo NO aplicarlas.

Principio: no se propone cambiar de tecnología «porque sí». Cada recomendación parte de un hallazgo concreto del código
y declara qué parte es inferencia. Si el repositorio no contiene la documentación o el contexto para decidir, lo dice.
"""
from __future__ import annotations

from ..models import Architecture, DebtFinding, Recommendation, Rule
from .common import Inventory


def build(inv: Inventory, arch: Architecture, debt: list[DebtFinding], rules: list[Rule]) -> list[Recommendation]:
    recs: list[Recommendation] = []
    by_title = lambda frag: next((d for d in debt if frag.lower() in d.title.lower()), None)

    def add(title, priority, effort, current, proposal, why, tradeoffs, not_when, related=()):
        recs.append(Recommendation(id="", title=title, priority=priority, effort=effort, current_state=current, proposal=proposal,
                                   justification=why, tradeoffs=tradeoffs, not_recommended_when=not_when, related_debt=list(related)))

    sec = by_title("Credenciales y secretos")
    conn = by_title("Cadenas de conexión (servidor")
    if sec or conn:
        add("Gestión de secretos y configuración por ambiente", "critical" if sec else "medium", "S",
            "Credenciales o cadenas de conexión viven en archivos del repositorio.",
            "Gestor de secretos (Azure Key Vault / AWS Secrets Manager / HashiCorp Vault) + identidad administrada cuando exista; "
            "configuración validada al arrancar; solo plantillas en el repo; escaneo de secretos en CI (gitleaks).",
            "Elimina la causa de la filtración (el secreto deja de existir en el código), permite rotarlo sin redeploy y separa responsabilidades "
            "entre quien desarrolla y quien opera. Es la corrección de mayor retorno por esfuerzo.",
            "Costo: bajo-medio (cuenta del gestor, permisos, cambio de despliegue). Requiere rotar credenciales ya expuestas y limpiar el historial de git.",
            "Un proyecto desechable sin datos reales y sin acceso a sistemas externos.", [d.id for d in (sec, conn) if d])

    ocr = by_title("OCR")
    if ocr:
        add("Pipeline de OCR desacoplado, medible y con revisión humana", ocr.severity, "M",
            "El OCR se ejecuta junto a la petición, sin medir confianza o sin resiliencia (ver hallazgo).",
            "Carga → almacenamiento → cola → worker de OCR → resultado + confianza por campo → validación de negocio → revisión humana solo de lo dudoso. "
            "Motor: si los documentos son estructurados (facturas, formularios) evaluar servicios gestionados de análisis de documentos "
            "(Azure AI Document Intelligence, AWS Textract, Google Document AI) frente a Tesseract/OpenCV propio; si no pueden salir del entorno, "
            "mantener Tesseract/PaddleOCR con preprocesamiento (deskew, binarización, 300 DPI).",
            "Los servicios gestionados extraen campos y tablas con modelos entrenados, entregan confianza por campo y se actualizan solos, lo que reduce "
            "las expresiones regulares frágiles. Desacoplar con cola evita bloquear la API y permite reintentos idempotentes y escalar workers por separado.",
            "Servicio gestionado: costo por página, dependencia del proveedor y envío de documentos a la nube (evaluar residencia de datos y la normativa "
            "aplicable si hay datos personales o sensibles). Tesseract propio: costo de infraestructura y mantenimiento, precisión menor en documentos ruidosos.",
            "Si el volumen es muy bajo y el OCR es auxiliar (no alimenta decisiones), basta con agregar umbral de confianza, timeout y preprocesamiento.", [ocr.id])

    q_mem = by_title("Colas en memoria")
    q_gov = by_title("Procesos encolados")
    if q_mem or q_gov:
        msg = ", ".join(arch.messaging) or "ninguno detectado"
        add("Procesamiento asíncrono durable y observable", "high" if q_mem else (q_gov.severity if q_gov else "medium"), "M",
            f"Trabajo en segundo plano con garantías débiles. Mensajería detectada: {msg}.",
            "Broker durable acorde al volumen (RabbitMQ / Azure Service Bus / SQS para colas de trabajo; Kafka solo si se requiere reproducción de eventos o "
            "alto volumen), patrón Outbox para publicar de forma atómica con la base de datos, DLQ con alerta, reintentos con espera exponencial e idempotencia. "
            "Si ya se usa Hangfire/Quartz, mantenerlo con almacenamiento persistente y panel protegido en vez de migrar.",
            "Las colas en memoria pierden trabajo al reiniciar; un broker durable mueve ese riesgo a una pieza diseñada para eso. Outbox evita el caso "
            "«se guardó en la base pero no se envió el mensaje». Mantener la herramienta actual cuando cumple reduce el costo de cambio.",
            "Costo: operar un broker (o pagarlo gestionado), cambios de diseño por idempotencia y mayor complejidad de pruebas.",
            "Procesos que toleran perderse (caché, notificaciones no críticas) o volúmenes mínimos donde un job en base de datos es suficiente.",
            [d.id for d in (q_mem, q_gov) if d])

    old = [d for d in debt if d.title.startswith("Tecnología desactualizada")]
    if old:
        add("Plan de actualización de plataforma por etapas", "high" if any(d.severity == "high" for d in old) else "medium", "L",
            "Se detectaron versiones fuera de soporte o cerca de terminarlo: " + "; ".join(d.title.split(": ", 1)[1] for d in old[:4]) + ".",
            "Actualizar de forma incremental con pruebas de caracterización previas: dependencias → framework → runtime (p. ej. .NET Upgrade Assistant, ng update). "
            "Priorizar versiones LTS vigentes.",
            "Sin parches de seguridad el riesgo crece cada mes y la mano de obra capaz de mantener versiones antiguas se encarece.",
            "Costo alto si no hay pruebas: por eso el plan empieza por proteger las reglas de negocio con pruebas (ver la recomendación de pruebas).",
            "Sistemas con fecha de retiro cercana y sin cambios previstos: puede ser más económico aislarlos y aplicar controles compensatorios.",
            [d.id for d in old])

    tests = by_title("pruebas")
    if tests:
        add("Red de seguridad: pruebas de caracterización sobre las reglas de negocio", "high" if tests.severity == "high" else "medium", "M",
            "Poca o ninguna cobertura de pruebas automáticas.",
            f"Convertir las {len(rules)} reglas extraídas en este informe en casos de prueba (empezando por «Restricción de negocio» y «Condición / umbral» "
            "con confianza alta/media), más pruebas de integración de los flujos principales y contract tests de las integraciones externas.",
            "Las reglas ya están enumeradas con su evidencia: sirven de backlog de pruebas. Con esa red es seguro refactorizar, actualizar versiones o cambiar de arquitectura.",
            "Costo: tiempo inicial del equipo; retorno: cada cambio posterior es más barato y seguro.", "Código que se va a descartar en el corto plazo.", [tests.id])

    god = by_title("Archivos gigantes")
    nodes_ctrl = arch.layers.get("Punto de entrada (API)", 0)
    biz_in_ctrl = [r for r in rules if r.category in ("Restricción de negocio", "Condición / umbral") and "controller" in r.evidence.file.lower()]
    if biz_in_ctrl and len(biz_in_ctrl) >= 8:
        add("Centralizar las reglas de negocio en una capa de dominio", "medium", "M",
            f"{len(biz_in_ctrl)} reglas parecen vivir dentro de controladores (capa de entrada). Es una inferencia por ubicación: valide que sean reglas "
            "de negocio y no manejo técnico de errores.",
            "Mover las reglas a servicios de dominio / casos de uso (y validadores) con pruebas unitarias; los controladores solo traducen HTTP.",
            "Las reglas en controladores no se pueden reutilizar (jobs, consumidores, otras APIs) y se duplican; centralizarlas deja una única fuente de verdad.",
            "Refactor gradual: un caso de uso por vez, sin cambiar el contrato público.", "APIs muy pequeñas con 1–2 reglas.")

    if "microservicios" in arch.style.lower():
        add("Observabilidad distribuida y contratos entre servicios", "medium", "M",
            f"{len(arch.deployables)} componentes desplegables" + ("; sin broker detectado (comunicación síncrona)." if not arch.messaging else "."),
            "Trazas distribuidas con OpenTelemetry, correlación de logs, health checks, versionado de contratos (OpenAPI/AsyncAPI) y límites de tiempo/circuit breakers.",
            "En microservicios los fallos son parciales; sin trazas es muy difícil encontrar qué servicio causó un error de punta a punta.",
            "Costo: instrumentación y un backend de observabilidad.",
            "Si los servicios comparten base de datos y se despliegan juntos, evaluar antes consolidarlos en un monolito modular.")
    elif len(arch.deployables) <= 1 and arch.layers.get("Lógica de negocio", 0) >= 15:
        add("Evolucionar como monolito modular (no saltar a microservicios)", "low", "M",
            "Un único componente desplegable con bastante lógica de negocio.",
            "Separar módulos por capacidad de negocio con límites explícitos (carpetas/ensamblados y reglas de dependencia verificadas con pruebas de arquitectura). "
            "Extraer a servicios solo los módulos con necesidad real de escalar o desplegarse de forma independiente.",
            "Aporta la mayor parte de los beneficios de orden y propiedad por equipo sin el costo operativo de la distribución (red, trazas, consistencia eventual).",
            "Costo: disciplina de límites. Microservicios solo si hay equipos independientes, escalado dispar o requisitos de aislamiento.",
            "Equipos de una o dos personas o sistemas con tráfico bajo y estable: microservicios añadirían complejidad sin beneficio.")

    ci = by_title("integración/entrega continua")
    sec_findings = [d for d in debt if d.category == "Seguridad" and d.severity in ("high", "critical")]
    if ci or sec_findings:
        add("Pipeline de entrega con controles de seguridad", "medium", "S",
            "Sin pipeline versionado" if ci else "Hay hallazgos de seguridad que un pipeline detectaría automáticamente.",
            "CI/CD con compilación, pruebas, SAST (CodeQL/Semgrep), análisis de dependencias (Dependabot/Renovate/OWASP dependency-check), "
            "escaneo de secretos y despliegue por ambientes con aprobación.",
            "Mueve la detección de riesgos al momento del cambio, cuando es más barato corregirlos, y hace repetibles los despliegues.",
            "Costo bajo con plataformas que traen estas funciones integradas.", "", [d.id for d in ([ci] if ci else []) + sec_findings[:3]])

    sqli = by_title("SQL")
    if sqli:
        add("Acceso a datos parametrizado", "high", "S", "Consultas SQL armadas por concatenación.",
            "Consultas parametrizadas u ORM con consultas tipadas; listas blancas para nombres dinámicos de columnas.",
            "Elimina la clase completa de vulnerabilidad de inyección SQL, en lugar de intentar «filtrar» entradas.",
            "Costo bajo por consulta; se puede hacer archivo por archivo.", "", [sqli.id])

    if by_title("Sin logging"):
        add("Logging estructurado y telemetría", "medium", "S", "Sin librerías de logging estructurado ni telemetría.",
            "Serilog/Logback/structlog/pino con correlación por petición + OpenTelemetry; alertas sobre errores y latencia.",
            "Permite responder qué falló, a quién afectó y desde cuándo, y cuantificar el impacto de los incidentes.", "Costo bajo; el volumen de logs requiere política de retención.", "")

    if not recs:
        add("Sin cambios estructurales recomendados por ahora", "low", "S",
            "No se detectaron hallazgos que justifiquen cambiar de arquitectura o tecnología con la información disponible.",
            "Mantener la arquitectura actual y atender la deuda técnica listada según su urgencia.",
            "Cambiar de tecnología sin una causa medible suma costo y riesgo sin beneficio demostrado.", "", "")

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: order[r.priority])
    for i, r in enumerate(recs, 1):
        r.id = f"RC-{i:02d}"
    return recs


LIMITATIONS = [
    "Es un análisis estático del código de la rama indicada: no ejecuta el sistema ni lo prueba contra datos reales.",
    "Las reglas que viven fuera del repositorio (procedimientos almacenados, configuración en la base de datos, parámetros en paneles de nube, reglas en sistemas externos) "
    "no son verificables desde el código y no aparecen aquí.",
    "Las reglas de confianza «media» o «baja» son inferencias a partir de condiciones del código; deben validarse con alguien que conozca el negocio.",
    "La deuda técnica se detecta por patrones: puede haber falsos positivos (p. ej. credenciales de ejemplo) y falsos negativos (problemas que no siguen un patrón conocido).",
    "No se auditan vulnerabilidades de dependencias (CVE) ni se mide cobertura real de pruebas; para eso se requiere integrar herramientas en el CI.",
    "Las fechas de fin de soporte de plataformas cambian: verifíquelas en la política oficial del fabricante.",
    "La evaluación de UI/UX se basa solo en el código: no mide el aspecto visual ni la experiencia real de las personas; para eso se requieren pruebas de uso.",
    "Se analiza una sola instantánea (el último commit de la rama): no se evalúa historial, rotación del equipo ni frecuencia de cambios.",
]
