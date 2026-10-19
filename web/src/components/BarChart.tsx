export interface Bar {
  label: string;
  value: number;
}

/**
 * Single-series horizontal bars on one axis starting at zero, in HTML so it reflows at 375 px and labels
 * wrap. The bars are a visual summary: the exact values are in the table rendered next to every chart.
 */
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
  return (
    <figure aria-label={title} className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">{title}</figcaption>
      <div className="space-y-1.5" aria-hidden="true">
        {bars.map((b) => (
          <div
            key={b.label}
            title={`${b.label}: ${format(b.value)}`}
            className="grid grid-cols-[minmax(6rem,9rem)_1fr_auto] items-center gap-2 text-sm"
          >
            <span className="break-words leading-tight">{b.label}</span>
            <span className="h-4 border-l border-rule">
              <span
                data-value={b.value}
                className="block h-full rounded-r bg-accent"
                style={{ width: `${Math.max(0, Math.min(100, (b.value / top) * 100))}%` }}
              />
            </span>
            <span className="tabular-nums text-muted">{format(b.value)}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}
