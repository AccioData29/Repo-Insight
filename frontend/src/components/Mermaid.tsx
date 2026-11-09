import { useEffect, useRef, useState } from "react";

let counter = 0;

/** Renderiza un diagrama Mermaid. securityLevel «strict» y sin HTML en etiquetas: el contenido proviene de nombres de código ajeno. */
export default function Mermaid({ code, title }: { code: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setErr(null);
    setLoading(true);
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        mermaid.initialize({
          startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default",
          flowchart: { htmlLabels: false, curve: "basis", useMaxWidth: true },
        });
        const { svg } = await mermaid.render(`mmd-${++counter}`, code);
        if (alive && ref.current) ref.current.innerHTML = svg;
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [code]);

  if (err) {
    return (
      <div className="alert alert-info">
        <p>No se pudo dibujar el diagrama. Se muestra su definición:</p>
        <pre className="code">{code}</pre>
      </div>
    );
  }
  return (
    <figure className="diagram">
      {loading && <p className="help">Dibujando diagrama…</p>}
      <div ref={ref} role="img" aria-label={title} className="diagram-canvas" />
    </figure>
  );
}
