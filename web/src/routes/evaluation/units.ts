export type Unit = "rate" | "ms" | "usd";

/** Units come from the metric's name suffix (`_ms`, `_usd`); everything else is a rate in [0, 1]. */
export function unitOf(key: string): Unit {
  if (/_ms$/.test(key)) return "ms";
  if (/_usd$/.test(key)) return "usd";
  return "rate";
}

export function fmt(key: string, value: number): string {
  const unit = unitOf(key);
  if (unit === "ms") return `${Math.round(value)} ms`;
  if (unit === "usd") return `$${value.toFixed(4)}`;
  return value.toFixed(3);
}
