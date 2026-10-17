export interface Bar {
  label: string;
  value: number;
}

const ROW = 28;
const LABEL_W = 120;
const VALUE_W = 56;
const WIDTH = 480;

/** Single-series horizontal bars (one axis, starts at zero). Hover shows the exact value; a table view sits beside it. */
export function BarChart({
  title,
  bars,
  max,
  format = (v) => v.toFixed(2),
}: {
  title: string;
  bars: Bar[];
  max?: number;
  format?: (value: number) => string;
}) {
  const top = Math.max(max ?? 0, ...bars.map((b) => b.value)) || 1;
  const plot = WIDTH - LABEL_W - VALUE_W;
  const height = bars.length * ROW;
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-sm font-medium">{title}</figcaption>
      <svg
        role="img"
        aria-label={title}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="w-full max-w-xl"
      >
        {bars.map((b, i) => {
          const w = Math.max(0, (b.value / top) * plot);
          const y = i * ROW + 6;
          const h = ROW - 12;
          const r = Math.min(4, w); // 4 px rounded data end; the baseline end stays square
          return (
            <g key={b.label}>
              <text
                x={LABEL_W - 8}
                y={y + h / 2}
                dominantBaseline="middle"
                textAnchor="end"
                fill="var(--crag-ink)"
                fontSize="12"
              >
                {b.label}
              </text>
              <path
                data-value={b.value}
                d={`M${LABEL_W},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${h - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - r)} z`}
                fill="var(--crag-accent)"
              >
                <title>{`${b.label}: ${format(b.value)}`}</title>
              </path>
              <rect
                data-value={b.value}
                x={LABEL_W}
                y={y - 4}
                width={plot}
                height={h + 8}
                fill="transparent"
              >
                <title>{`${b.label}: ${format(b.value)}`}</title>
              </rect>
              <text
                x={LABEL_W + w + 6}
                y={y + h / 2}
                dominantBaseline="middle"
                fill="var(--crag-ink-muted)"
                fontSize="12"
              >
                {format(b.value)}
              </text>
            </g>
          );
        })}
        <line
          x1={LABEL_W}
          x2={LABEL_W}
          y1={0}
          y2={height}
          stroke="var(--crag-rule)"
          strokeWidth={1}
        />
      </svg>
    </figure>
  );
}
