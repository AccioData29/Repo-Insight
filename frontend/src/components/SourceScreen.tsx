import { useEffect, useMemo, useRef, useState } from "react";
import { getConfig, startAnalysis, validateSource } from "../api";
import type { AppConfig, Platform, Privacy, SourceValidation } from "../types";

const PLATFORM_OPTIONS: { id: Platform | ""; label: string }[] = [
  { id: "", label: "Detectar automáticamente" },
  { id: "github", label: "GitHub" },
  { id: "gitlab", label: "GitLab" },
  { id: "azure_devops", label: "Azure DevOps" },
  { id: "bitbucket", label: "Bitbucket" },
];

const PRIVACY_OPTIONS: { id: Privacy; label: string; hint: string }[] = [
  { id: "unknown", label: "No lo sé (detectar)", hint: "El sistema lo comprueba por usted." },
  { id: "public", label: "Público", hint: "No se pide ningún permiso." },
  { id: "private", label: "Privado", hint: "Se pedirá un token de solo lectura." },
];

const PRIVACY_TEXT: Record<Privacy, string> = { public: "Público", private: "Privado", unknown: "Sin determinar" };

export default function SourceScreen({ onStarted }: { onStarted: (jobId: string) => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [url, setUrl] = useState("");
  const [platform, setPlatform] = useState<Platform | "">("");
  const [privacy, setPrivacy] = useState<Privacy>("unknown");
  const [token, setToken] = useState("");
  const [branch, setBranch] = useState("");
  const [ai, setAi] = useState(false);
  const [v, setV] = useState<SourceValidation | null>(null);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => { getConfig().then(setCfg).catch(() => setCfg(null)); }, []);

  const runValidation = async (withToken: boolean) => {
    if (!url.trim()) { setV(null); return; }
    const mine = ++seq.current;
    setChecking(true);
    try {
      const res = await validateSource({ url: url.trim(), platform: platform || null, privacy, token: withToken ? token : null });
      if (mine !== seq.current) return;
      setV(res);
      setError(null);
      if (res.production_branch && !branch) setBranch(res.production_branch);
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setChecking(false);
    }
  };

  // validación automática (con espera) al escribir el enlace o cambiar plataforma/privacidad
  useEffect(() => {
    setBranch("");
    const t = setTimeout(() => { void runValidation(false); }, 650);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, platform, privacy]);

  const canAnalyze = useMemo(() => !!v && v.valid && v.accessible && !starting, [v, starting]);

  const submit = async () => {
    if (!v) return;
    setStarting(true);
    setError(null);
    try {
      const job = await startAnalysis({
        url: url.trim(), platform: platform || null, branch: branch || null, privacy,
        token: v.needs_token ? token : null, ai_enrichment: ai,
      });
      setToken("");                       // el token ya no se conserva en el navegador
      onStarted(job.id);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  const mismatch = v?.valid && privacy !== "unknown" && v.privacy_detected !== "unknown" && privacy !== v.privacy_detected;

  return (
    <div className="container narrow">
      <section className="hero">
        <h1>Reglas de negocio, flujo y deuda técnica de su repositorio</h1>
        <p className="lead">
          Indique el repositorio. Analizamos <strong>la rama de producción en modo solo lectura</strong> y le entregamos un informe
          que entienden tanto el equipo técnico como el de negocio.
        </p>
      </section>

      <form className="card form" onSubmit={(e) => { e.preventDefault(); if (canAnalyze) void submit(); }}>
        <div className="field">
          <label htmlFor="url">Enlace del repositorio</label>
          <input id="url" type="url" inputMode="url" autoComplete="off" spellCheck={false} placeholder="https://github.com/organizacion/repositorio"
                 value={url} onChange={(e) => setUrl(e.target.value)} aria-describedby="url-help" />
          <p id="url-help" className="help">Se valida que el enlace corresponda realmente a la plataforma. Solo se aceptan enlaces https.</p>
        </div>

        <div className="grid2">
          <div className="field">
            <label htmlFor="platform">Plataforma</label>
            <select id="platform" value={platform} onChange={(e) => setPlatform(e.target.value as Platform | "")}>
              {PLATFORM_OPTIONS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
            <div className="status-row" aria-live="polite">
              {checking && <span className="chip chip-muted">Comprobando…</span>}
              {!checking && v?.valid && <span className="chip chip-ok">✓ {v.platform_label}: enlace válido</span>}
              {!checking && v && !v.valid && <span className="chip chip-bad">✕ Enlace no válido</span>}
            </div>
          </div>

          <fieldset className="field">
            <legend>Privacidad del repositorio</legend>
            <div className="radios">
              {PRIVACY_OPTIONS.map((o) => (
                <label key={o.id} className={`radio ${privacy === o.id ? "on" : ""}`}>
                  <input type="radio" name="privacy" value={o.id} checked={privacy === o.id} onChange={() => setPrivacy(o.id)} />
                  <span><strong>{o.label}</strong><small>{o.hint}</small></span>
                </label>
              ))}
            </div>
            {!checking && v?.valid && (
              <div className="status-row" aria-live="polite">
                <span className={`chip ${v.privacy_detected === "public" ? "chip-ok" : "chip-warn"}`}>
                  Detectado: {PRIVACY_TEXT[v.privacy_detected]}
                </span>
              </div>
            )}
          </fieldset>
        </div>

        {v && v.errors.length > 0 && <div className="alert alert-bad" role="alert">{v.errors.map((m) => <p key={m}>{m}</p>)}</div>}
        {v && v.messages.length > 0 && !v.errors.length && (
          <div className={`alert ${v.accessible ? "alert-ok" : "alert-info"}`}>{v.messages.map((m) => <p key={m}>{m}</p>)}</div>
        )}
        {mismatch && <div className="alert alert-info"><p>Usted indicó «{PRIVACY_TEXT[privacy]}», pero el repositorio es {PRIVACY_TEXT[v!.privacy_detected].toLowerCase()}: se usará lo detectado.</p></div>}

        {v?.needs_token && v.permission && (
          <div className="permission" role="group" aria-labelledby="perm-title">
            <h2 id="perm-title">🔐 Permiso requerido (solo lectura)</h2>
            <p>Este repositorio exige credenciales. Cree un <strong>{v.permission.token_kind}</strong> con el mínimo permiso necesario:</p>
            <ul className="chips" aria-label="Permisos necesarios">
              {v.permission.scopes.map((s) => <li key={s} className="chip chip-scope">{s}</li>)}
            </ul>
            <ol className="steps">{v.permission.steps.map((s) => <li key={s}>{s}</li>)}</ol>
            {v.permission.note && <p className="help">{v.permission.note}</p>}
            <p><a className="link" href={v.permission.create_url} target="_blank" rel="noopener noreferrer">Abrir la página para crear el token ↗</a></p>
            <div className="field">
              <label htmlFor="token">Token de acceso</label>
              <div className="inline">
                <input id="token" type="password" autoComplete="off" spellCheck={false} value={token} onChange={(e) => setToken(e.target.value)} placeholder="Pegue aquí el token" />
                <button type="button" className="btn btn-secondary" disabled={!token || checking} onClick={() => void runValidation(true)}>Verificar acceso</button>
              </div>
              <p className="help">El token solo se usa en memoria para clonar y se descarta al terminar. No se guarda ni se registra, y el código descargado se elimina al finalizar el análisis.</p>
            </div>
          </div>
        )}

        {v?.accessible && (
          <div className="field">
            <label htmlFor="branch">Rama de producción</label>
            {v.branches.length > 0 ? (
              <select id="branch" value={branch} onChange={(e) => setBranch(e.target.value)}>
                {v.branches.map((b) => <option key={b} value={b}>{b}{b === v.production_branch ? "  (sugerida)" : ""}</option>)}
              </select>
            ) : (
              <input id="branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
            )}
            {v.production_branch_reason && <p className="help">{v.production_branch_reason}</p>}
          </div>
        )}

        {cfg?.ai_available && (
          <label className="check">
            <input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} />
            <span>
              <strong>Redactar las reglas en lenguaje de negocio con IA (opcional)</strong>
              <small>Envía a Claude solo fragmentos mínimos de reglas ya extraídas (sin secretos, nunca el repositorio completo). Si no lo activa, todo se procesa localmente.</small>
            </span>
          </label>
        )}

        {error && <div className="alert alert-bad" role="alert"><p>{error}</p></div>}

        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={!canAnalyze}>{starting ? "Iniciando…" : "Analizar repositorio"}</button>
          {!canAnalyze && <span className="help">{!v ? "Ingrese un enlace para comenzar." : !v.valid ? "Corrija el enlace." : !v.accessible ? "Falta acceso al repositorio." : ""}</span>}
        </div>
      </form>

      <ul className="trust" aria-label="Garantías">
        <li><strong>Solo lectura.</strong> Nunca se modifica el repositorio.</li>
        <li><strong>Sin historial.</strong> Se descarga únicamente el último commit de la rama.</li>
        <li><strong>Sin retención.</strong> El código descargado se elimina al terminar.</li>
        <li><strong>Secretos ocultos.</strong> Las credenciales encontradas nunca aparecen en el informe.</li>
      </ul>
    </div>
  );
}
