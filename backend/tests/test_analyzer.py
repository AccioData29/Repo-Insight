import json

from app.analyzer import debt, flows, rules as rules_mod
from app.analyzer.common import Inventory, humanize_condition, redact, words
from app.analyzer.engine import analyze_directory


def titles(findings):
    return {f.title: f for f in findings}


def test_redact_hides_secrets():
    assert "Sup3rS3cret" not in redact("Host=x;Password=Sup3rS3cret!;")
    assert "abc123" not in redact("API_KEY=abc123def456ghi789")
    assert "AKIA" not in redact("key AKIAABCDEFGHIJKLMNOP end")


def test_humanize():
    assert words("ValidarMontoFactura") == "validar monto factura"
    h = humanize_condition("r.Total > 1000000 && r.Items.Count > 10")
    assert "mayor que 1000000" in h and " y " in h
    assert "«blocked»" in humanize_condition("r.Customer.Status == CustomerStatus.Blocked").lower() or "blocked" in humanize_condition("x == CustomerStatus.Blocked")


def test_debt_detects_seeded_problems(sample_repo):
    inv = Inventory(sample_repo)
    found = debt.run_all(inv)
    ts = " | ".join(f.title for f in found)
    assert "Credenciales y secretos versionados" in ts
    assert "inyección SQL" in ts
    assert "OCR" in ts
    assert "Colas en memoria" in ts
    assert "Procesos encolados" in ts
    assert "TLS" in ts
    assert "desactualizada" in ts and ".NET (net6.0)" in ts and "Angular 12" in ts
    assert "Errores silenciados" in ts
    assert "sin autenticación" not in ts.lower()          # sí hay [Authorize] en el repo
    sev = {f.title: f.severity for f in found}
    assert sev["Credenciales y secretos versionados en el repositorio"] == "critical"
    # orden por urgencia
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert [order[f.severity] for f in found] == sorted(order[f.severity] for f in found)


def test_no_secret_value_appears_anywhere_in_report(sample_repo):
    rep = analyze_directory(sample_repo, dict(url="u", branch="main", owner="o", repo="r"))
    blob = rep.model_dump_json()
    for secret in ("Sup3rS3cret", "devpass123", "Sa123456", "abc123def456ghi789"):
        assert secret not in blob, secret


def test_connection_strings_in_config_are_debt(sample_repo):
    inv = Inventory(sample_repo)
    ev_files = {e.file for f in debt.run_all(inv) if "Credenciales" in f.title for e in f.evidence}
    assert any(f.endswith("appsettings.json") for f in ev_files)
    assert any(f.endswith("web.config") for f in ev_files)
    assert ".env" in ev_files


def test_ocr_issues_listed(sample_repo):
    f = [x for x in debt.run_all(Inventory(sample_repo)) if "OCR" in x.title][0]
    assert f.severity in ("high", "medium")
    assert "petición HTTP" in f.technical_detail or "desacople" in f.technical_detail
    assert "confianza" in f.technical_detail
    assert "regulares" in f.technical_detail


def test_rules_extracted(sample_repo):
    rl = rules_mod.extract_rules(Inventory(sample_repo))
    cats = {r.category for r in rl}
    assert {"Validación de datos", "Restricción de negocio", "Autorización y roles", "Estado y transición",
            "Parámetro configurable", "Restricción en base de datos", "Proceso programado"} <= cats
    biz = " ".join(r.description for r in rl if r.category == "Restricción de negocio")
    assert "cliente bloqueado" in biz and "supera el máximo" in biz
    assert any("Contador" in r.description and "Administrador" in r.description for r in rl)
    num = [r for r in rl if r.category == "Validación de datos" and "number" in r.description.lower()][0]
    assert "es obligatorio" in num.description and "máximo 20 caracteres" in num.description
    assert any(r.category == "Parámetro configurable" and "50000000" in r.condition for r in rl)
    assert all(r.id.startswith("R-") and r.evidence.line >= 1 for r in rl)
    # la regla con condición debe traducirla a lenguaje natural
    cond = [r for r in rl if "cliente bloqueado" in r.description][0]
    assert "cuando" in cond.description


def test_entry_points_and_flows(sample_repo):
    inv = Inventory(sample_repo)
    eps = flows.find_entry_points(inv)
    routes = {(e.method, e.route) for e in eps if e.kind == "API"}
    assert ("POST", "/api/invoices/scan") in routes and ("GET", "/api/invoices/{id}") in routes
    assert any(e.kind == "Proceso en segundo plano" for e in eps)
    rl = rules_mod.extract_rules(inv)
    fl = flows.build_flows(inv, eps, rl)
    assert fl
    f = fl[0]
    names = [s.name for s in f.steps]
    assert "InvoicesController" in names and "InvoiceService" in names and "InvoiceRepository" in names
    assert any("Base de datos" == e for e in f.externals) or any("API externa" in e for e in f.externals)
    assert f.mermaid.startswith("flowchart LR") and "-->" in f.mermaid
    assert f.rule_ids


def test_architecture_and_report_roundtrip(sample_repo):
    rep = analyze_directory(sample_repo, dict(url="u", branch="main", owner="o", repo="r"))
    assert any(l.language == "C#" for l in rep.architecture.languages)
    assert "PostgreSQL" in rep.architecture.data_stores
    assert "Angular" in rep.architecture.frameworks and "Tesseract OCR" in rep.architecture.frameworks
    assert rep.summary.risk_level == "critical"
    assert any("OCR" in r.title for r in rep.recommendations)
    assert any("secretos" in r.title.lower() for r in rep.recommendations)
    assert "Según el README" in rep.summary.what_it_does
    json.loads(rep.model_dump_json())          # serializable


# ---------- regresiones encontradas al revisar la salida real ----------
def test_allow_anonymous_is_attributed_to_the_right_method(sample_repo):
    """Bug: el método con cuerpo `=>` no se reconocía y la regla se asignaba al método siguiente."""
    rl = rules_mod.extract_rules(Inventory(sample_repo))
    anon = [r for r in rl if "sin iniciar sesión" in r.description]
    assert len(anon) == 1 and "get" in anon[0].description.lower() and "create" not in anon[0].description.lower()


def test_method_name_detection():
    mn = rules_mod.method_name
    assert mn("        public IActionResult Get(int id) => Ok(_service.Find(id));") == "Get"
    assert mn("        public async Task<IActionResult> Scan(IFormFile file)") == "Scan"
    assert mn("            return Ok(result);") == ""
    assert mn("            await _tax.Send(inv);") == ""
    assert mn("    def calcular_total(self, x):") == "calcular_total"
    assert mn("        var x = foo(bar);") == ""


def test_sql_check_and_unique_are_separate_rules(sample_repo):
    rl = [r for r in rules_mod.extract_rules(Inventory(sample_repo)) if r.category == "Restricción en base de datos" and r.evidence.file.endswith(".sql")]
    check = [r for r in rl if r.title == "Restricción CHECK"][0]
    uniq = [r for r in rl if r.title == "Valor único"][0]
    assert "UNIQUE" not in check.description and check.condition.strip() == "total > 0"
    assert "number" in uniq.description.lower()


def test_hangfire_recurring_job_detected(sample_repo):
    rl = [r for r in rules_mod.extract_rules(Inventory(sample_repo)) if r.category == "Proceso programado"]
    assert any("daily" in r.description.lower() for r in rl)
    assert all("execute async" not in r.description.lower() for r in rl)      # usa el nombre de la clase


def test_summary_language_list_not_broken(sample_repo):
    rep = analyze_directory(sample_repo, dict(url="u", branch="main", owner="o", repo="r"))
    assert "C#. SQL" not in rep.summary.what_it_does


def test_externals_not_duplicated(sample_repo):
    inv = Inventory(sample_repo)
    eps = flows.find_entry_points(inv)
    f = flows.build_flows(inv, eps, rules_mod.extract_rules(inv))[0]
    assert "API externa" not in f.externals and any(e.startswith("API externa: ") for e in f.externals)
    assert "ocr" not in f.narrative.split("Interactúa con:")[-1].split(", ")      # sin minúsculas forzadas


# ---------- regresión: resolución de interfaces (hallada con eShopOnWeb) ----------
def _mk(tmp_path, files):
    for rel, c in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c)
    return Inventory(tmp_path)


def test_interface_resolution_ignores_generic_args_and_ambiguous_interfaces(tmp_path):
    inv = _mk(tmp_path, {
        "Api/IEndpoint.cs": "public interface IEndpoint<T> { }",
        "Api/AEndpoint.cs": "public class AEndpoint : IEndpoint<IRepository<Foo>> { public AEndpoint(IRepository<Foo> r) {} }",
        "Api/BEndpoint.cs": "public class BEndpoint : IEndpoint<Bar> { public BEndpoint(IRepository<Foo> r) {} }",
        "Api/CEndpoint.cs": "public class CEndpoint(IRepository<Foo> r) : IEndpoint<Bar> { }",       # constructor primario C# 12
        "Core/IRepository.cs": "public interface IRepository<T> { }",
        "Infra/EfRepository.cs": "public class EfRepository<T> : IRepository<T> { private DbContext c; }",
    })
    nodes, edges = flows.build_graph(inv)
    for ep in ("AEndpoint", "BEndpoint", "CEndpoint"):
        assert "EfRepository" in edges[ep], ep                       # IRepository -> su única implementación
        assert not ({"AEndpoint", "BEndpoint", "CEndpoint"} & edges[ep]), ep   # IEndpoint (ambigua) no enlaza endpoints entre sí
    assert "Base de datos" in nodes["EfRepository"].externals
