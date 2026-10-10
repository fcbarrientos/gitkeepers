/** Lightweight charts built from plain elements: no chart package, readable without colour. */

export type Datum = { label: string; value: number; tip: string; highlight?: boolean };

/** Vertical columns, one per datum, with the value printed on each column. */
export function ColumnChart({ data, summary }: { data: Datum[]; summary: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <figure className="columns" aria-label={summary} role="img">
      {data.map((d) => (
        <div key={d.label} className={`column${d.highlight ? " is-today" : ""}`} data-tip={d.tip} title={d.tip}>
          <span className="column-value">{d.value}</span>
          <span className="column-track"><span className="column-bar" style={{ height: `${(d.value / max) * 100}%` }} /></span>
          <span className="column-label">{d.label}</span>
        </div>
      ))}
    </figure>
  );
}

/** Horizontal bars that share one scale; each row shows its label and count. */
export function BarList({ data }: { data: Datum[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="barlist">
      {data.map((d) => (
        <li key={d.label} title={d.tip}>
          <span className="barlist-label">{d.label}</span>
          <span className="barlist-value">{d.value}</span>
          <span className="barlist-track" aria-hidden="true"><span style={{ width: `${(d.value / max) * 100}%` }} /></span>
        </li>
      ))}
    </ul>
  );
}

export type Segment = { key: string; label: string; value: number; tone: "danger" | "warn" | "info" | "ok" };

/** One stacked bar with a legend underneath (counts are always written out). */
export function StackedBar({ segments, label }: { segments: Segment[]; label: string }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  return (
    <div className="stacked">
      <div className="stacked-bar" role="img" aria-label={label}>
        {total > 0 && segments.filter((s) => s.value > 0).map((s) => (
          <span key={s.key} className={`seg seg-${s.tone}`} style={{ flexGrow: s.value }} title={`${s.label}: ${s.value}`} />
        ))}
      </div>
      <ul className="legend">
        {segments.map((s) => (
          <li key={s.key}><span className={`dot seg-${s.tone}`} aria-hidden="true" />{s.label} <strong>{s.value}</strong></li>
        ))}
      </ul>
    </div>
  );
}
