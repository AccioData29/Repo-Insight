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


# --- Regresiones encontradas al probar un repo real (app móvil React Native) -------------
def _mini_repo(tmp_path, files: dict):
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def _run(tmp_path):
    return analyze_directory(tmp_path, dict(url="u", branch="main", owner="o", repo="r"))


def test_error_codes_and_fixtures_are_not_secrets(tmp_path):
    repo = _mini_repo(tmp_path, {
        "app/src/auth/validation.ts": "export function v(errors: any) {\n  errors.password = 'password_policy';\n  if (errors.password === 'required') {}\n}\n",
        "app/testing/fixtures.ts": "export const password = 'Clave123!';\n",
        "app/src/ui/LoginScreen.tsx": "export function LoginScreen() {\n  const e = validateLoginInput(identifier, password);\n  return null;\n}\n",
    })
    rep = _run(repo)
    titles = [d.title for d in rep.debt]
    assert not any("Credenciales" in t for t in titles)
    assert not any("registro de contraseñas" in t for t in titles)


def test_real_hardcoded_secret_still_detected(tmp_path):
    repo = _mini_repo(tmp_path, {"src/db.ts": "const dbPassword = 'Pr0d-S3cret!99';\n"})
    assert any("Credenciales" in d.title for d in _run(repo).debt)


def test_screens_become_flows_without_router(tmp_path):
    repo = _mini_repo(tmp_path, {
        "app/src/presentation/login/LoginScreen.tsx": "import { loginAccount } from '../../services/accountLogin';\nexport function LoginScreen() { return loginAccount(); }\n",
        "app/src/services/accountLogin.ts": "import { db } from '../infrastructure/database/encryptedDatabase';\nexport function loginAccount() { return db; }\n",
        "app/src/infrastructure/database/encryptedDatabase.ts": "export const db = {};\n",
    })
    rep = _run(repo)
    assert rep.flows, "debe haber al menos un flujo por pantalla"
    assert [s.name for s in rep.flows[0].steps][:2] == ["LoginScreen", "accountLogin"]


def test_commented_catch_and_login_call_are_not_debt(tmp_path):
    repo = _mini_repo(tmp_path, {
        "src/a.ts": "async function f(gateway: any, identifier: string, password: string) {\n  try { x(); } catch {\n    // Un fallo del OCR equivale a no haber identificado datos.\n  }\n  return gateway.login(identifier, password);\n}\n",
        "src/b.ts": "function g() { try { x(); } catch {} }\n",
    })
    titles = [d.title for d in _run(repo).debt]
    assert not any("registro de contraseñas" in t for t in titles)
    sw = [d for d in _run(repo).debt if "silenciados" in d.title][0]
    assert sw.occurrences == 1      # solo el catch vacío sin explicación


# --- UI/UX ------------------------------------------------------------------------------
def test_ux_not_applicable_for_backend_only(sample_repo):
    rep = analyze_directory(sample_repo, dict(url="u", branch="main", owner="o", repo="r"))
    assert rep.ux is not None and rep.ux.applicable is False and rep.ux.verdict == "no_aplica"


def test_ux_flags_inaccessible_web_form(tmp_path):
    repo = _mini_repo(tmp_path, {
        "src/App.tsx": (
            "export function App() {\n  return (<div>\n"
            "    <img src='a.png' />\n"
            "    <div onClick={go}>Enviar</div>\n"
            "    <input type='text' /><input type='text' /><input type='text' />\n"
            "    <button onClick={go}>OK</button>\n"
            "  </div>);\n}\n"),
    })
    ux = _run(repo).ux
    assert ux.applicable and "web" in ux.surface.lower()
    titles = {f.title for f in ux.findings}
    assert "Imágenes con texto alternativo" in titles
    assert "Elementos clicables con semántica correcta" in titles
    assert ux.verdict in ("mejorable", "deficiente")


def test_ux_good_practices_recognized(tmp_path):
    repo = _mini_repo(tmp_path, {
        "app/src/ui/LoginScreen.tsx": (
            "import { View, TextInput, Pressable, ActivityIndicator, KeyboardAvoidingView } from 'react-native';\n"
            "export function LoginScreen() {\n  const [loading, setLoading] = useState(false);\n  const [error, setError] = useState('');\n"
            "  return (<KeyboardAvoidingView>\n"
            "    <TextInput accessibilityLabel='Correo' keyboardType='email-address' />\n"
            "    <TextInput accessibilityLabel='Clave' secureTextEntry />\n"
            "    <Pressable accessibilityRole='button' accessibilityLabel='Entrar' disabled={loading} onPress={go}/>\n"
            "    {loading && <ActivityIndicator/>}{error ? <Text accessibilityRole='alert'>{error}</Text> : null}\n"
            "  </KeyboardAvoidingView>);\n}\n"),
    })
    ux = _run(repo).ux
    dims = {d.id: d.status for d in ux.dimensions}
    assert dims["accesibilidad"] == "bueno" and dims["formularios"] in ("bueno", "aceptable")
    assert [n.lower() for n in ux.screen_names] == ["login"]


# --- Autoría (git real en un directorio temporal) ------------------------------------------
import subprocess as _sp


def _git_repo(tmp_path, commits):
    """commits: lista de (autor, mensaje, {ruta: contenido})."""
    def g(*a, env=None):
        _sp.run(["git", "-C", str(tmp_path), "-c", "commit.gpgsign=false", *a], check=True, capture_output=True, env=env)
    _sp.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    import os
    for i, (author, msg, files) in enumerate(commits):
        for rel, body in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        g("add", "-A")
        env = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author.lower().replace(' ', '.')}@example.org",
               "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": f"{author.lower().replace(' ', '.')}@example.org",
               "GIT_AUTHOR_DATE": f"2026-01-{i + 1:02d}T10:00:00+00:00", "GIT_COMMITTER_DATE": f"2026-01-{i + 1:02d}T10:00:00+00:00"}
        g("commit", "-q", "-m", msg, env=env)
    return tmp_path


def test_authorship_counts_ai_coauthored_and_human_lines(tmp_path):
    ai_body = "\n".join(f"export const v{i} = {i};" for i in range(80)) + "\n"
    repo = _git_repo(tmp_path, [
        ("Ana Perez", "feat: modulo\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>", {"src/a.ts": ai_body}),
        ("Luis Gomez", "fix: ajusta valores", {"src/b.ts": "export const humano = 1;\nexport const otro = 2;\n"}),
        ("Luis Gomez", "docs: lee", {"README.md": "# Proyecto\n"}),
    ])
    a = _run(repo).authorship
    assert a.available and a.commits == 3
    assert a.tools and a.tools[0].tool.startswith("Claude")
    assert 90 < a.ai_pct < 99                       # 80 líneas de IA frente a 3 humanas
    names = {c.name: c for c in a.collaborators}
    assert names["Ana Perez"].ai_declared_commits == 1 and names["Ana Perez"].ai_share_pct == 100
    assert names["Luis Gomez"].ai_share_pct == 0 and names["Luis Gomez"].commits == 2
    assert a.verdict == "ia_mayoritaria"
    assert "@" not in a.model_dump_json().replace("noreply@anthropic.com", "")   # no se exponen correos


def test_authorship_human_edits_raise_intervention(tmp_path):
    body = "\n".join(f"line{i} = {i}" for i in range(40)) + "\n"
    edited = "\n".join(f"line{i} = {i + 1}" if i % 2 == 0 else f"line{i} = {i}" for i in range(40)) + "\n"
    repo = _git_repo(tmp_path, [
        ("Ana Perez", "feat\n\nCo-Authored-By: Claude <noreply@anthropic.com>", {"core.py": body}),
        ("Luis Gomez", "refactor propio", {"core.py": edited}),
    ])
    a = _run(repo).authorship
    assert a.intervention_level == "alta"
    assert a.verdict in ("mixto", "humano_con_apoyo_ia")


def test_authorship_no_ai_means_no_evidence(tmp_path):
    repo = _git_repo(tmp_path, [("Ana Perez", "init", {"a.py": "x = 1\ny = 2\n"})])
    a = _run(repo).authorship
    assert a.verdict == "sin_evidencia" and a.intervention_level == "no_medible" and a.ai_pct == 0


def test_authorship_unavailable_without_git(tmp_path):
    repo = _mini_repo(tmp_path, {"a.py": "x = 1\n"})
    a = _run(repo).authorship
    assert a is not None and a.available is False


def test_markdown_export_includes_ux_and_authorship(tmp_path):
    from app.export import to_markdown
    repo = _git_repo(tmp_path, [("Ana Perez", "feat\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                                 {"src/App.tsx": "export function App() { return (<div><button onClick={go}>OK</button></div>); }\n"})])
    md = to_markdown(_run(repo))
    assert "## UI/UX" in md and "## Autoría: IA y equipo" in md
