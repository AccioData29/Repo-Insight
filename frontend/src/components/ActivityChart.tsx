import { useState } from "react";
import type { TeamTimeline, TimelineSeries } from "../types";

type Metric = "commits" | "added";
const COLOR = { persona: "var(--low)", ia: "var(--accent)", bot: "var(--muted)" } as const;
const KIND = { persona: "Persona", ia: "Herramienta de IA", bot: "Automatización" } as const;
const nf = (x: number) => x.toLocaleString("es-CO");

function niceMax(v: number): number {
  if (v <= 4) return Math.max(v, 1);
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return v;
}
const day = (iso: string, monthly: boolean) =>
  new Date(iso + "T00:00:00").toLocaleDateString("es-CO", monthly ? { month: "short", year: "2-digit" } : { day: "numeric", month: "short" });

function Bars({ values, buckets, color, monthly, height, label, unit, xLabels }: {
  values: number[]; buckets: string[]; color: string; monthly: boolean; height: number; label: string; unit: string; xLabels: boolean;
}) {
  const W = 640, padL = 44, padR = 8, padT = 8, padB = xLabels ? 24 : 6;
  const H = height, plotW = W - padL - padR, plotH = H - padT - padB;
  const max = niceMax(Math.max(...values, 1));
  const bw = plotW / values.length;
  const ticks = [0, max / 2, max];
  const step = Math.ceil(values.length / 8);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={label}>
      {ticks.map((t) => {
        const y = padT + plotH - (t / max) * plotH;
        return (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y} y2={y} className="grid" />
            <text x={padL - 6} y={y + 4} textAnchor="end" className="axis">{nf(Math.round(t))}</text>
          </g>
        );
      })}
      {values.map((v, i) => {
        const h = (v / max) * plotH;
        return (
          <rect key={buckets[i]} x={padL + i * bw + 1} y={padT + plotH - h} width={Math.max(1, bw - 2)} height={h} style={{ fill: color }} rx={2}>
            <title>{`${monthly ? "Mes" : "Semana"} del ${day(buckets[i], monthly)}: ${nf(v)} ${unit}`}</title>
          </rect>
        );
      })}
      {xLabels && buckets.map((b, i) => (i % step === 0 ? (
        <text key={b} x={padL + i * bw + bw / 2} y={H - 6} textAnchor="middle" className="axis">{day(b, monthly)}</text>
      ) : null))}
    </svg>
  );
}

function Mini({ s, tl, metric }: { s: TimelineSeries; tl: TeamTimeline; metric: Metric }) {
  const monthly = tl.granularity === "mes";
  const values = metric === "commits" ? s.commits : s.added;
  const unit = metric === "commits" ? "commits" : "líneas agregadas";
  return (
    <li className="card mini">
      <div className="row-between">
        <div><strong>{s.name}</strong><div className="meta">{KIND[s.kind]} · {s.role}</div></div>
        <div className="meta mini-total"><strong>{nf(metric === "commits" ? s.total_commits : s.total_added)}</strong> {unit}</div>
      </div>
      <Bars values={values} buckets={tl.buckets} color={COLOR[s.kind]} monthly={monthly} height={110} xLabels={false}
            label={`${s.name}: ${nf(s.total_commits)} commits y ${nf(s.total_added)} líneas agregadas por ${tl.granularity}`} unit={unit} />
    </li>
  );
}

export default function ActivityChart({ tl }: { tl: TeamTimeline }) {
  const [metric, setMetric] = useState<Metric>("commits");
  const monthly = tl.granularity === "mes";
  const total = metric === "commits" ? tl.total_commits : tl.total_added;
  const unit = metric === "commits" ? "commits" : "líneas agregadas";
  const sum = total.reduce((a, b) => a + b, 0);
  return (
    <div className="stack">
      <div className="row-between wrap">
        <div className="seg" role="group" aria-label="Métrica de la gráfica">
          <button className={metric === "commits" ? "on" : ""} onClick={() => setMetric("commits")}>Commits</button>
          <button className={metric === "added" ? "on" : ""} onClick={() => setMetric("added")}>Líneas agregadas</button>
        </div>
        <ul className="legend2">
          <li><span className="dot seg-human" /> Persona</li><li><span className="dot seg-ai" /> Herramienta de IA</li>
          {tl.series.some((s) => s.kind === "bot") && <li><span className="dot seg-bot" /> Automatización</li>}
        </ul>
      </div>
      <div>
        <h3>Total del repositorio: {nf(sum)} {unit} por {tl.granularity}</h3>
        <Bars values={total} buckets={tl.buckets} color="var(--muted)" monthly={monthly} height={200} xLabels
              label={`Total de ${unit} por ${tl.granularity}, de ${day(tl.buckets[0], monthly)} a ${day(tl.buckets[tl.buckets.length - 1], monthly)}: ${nf(sum)}`} unit={unit} />
      </div>
      <h3>Por colaborador</h3>
      <ul className="cards mini-grid">{tl.series.slice(0, 8).map((s) => <Mini key={s.name} s={s} tl={tl} metric={metric} />)}</ul>
      {tl.series.length > 8 && <p className="help">Se muestran los 8 colaboradores con más actividad.</p>}
      <details>
        <summary>Ver los datos en tabla</summary>
        <div className="table-wrap"><table>
          <thead><tr><th>{monthly ? "Mes" : "Semana"} del</th><th>Total</th>{tl.series.slice(0, 8).map((s) => <th key={s.name}>{s.name}</th>)}</tr></thead>
          <tbody>{tl.buckets.map((b, i) => (
            <tr key={b}><td>{day(b, monthly)}</td><td>{nf(total[i])}</td>{tl.series.slice(0, 8).map((s) => <td key={s.name}>{nf((metric === "commits" ? s.commits : s.added)[i])}</td>)}</tr>
          ))}</tbody>
        </table></div>
      </details>
      <p className="help">{tl.note}</p>
    </div>
  );
}
