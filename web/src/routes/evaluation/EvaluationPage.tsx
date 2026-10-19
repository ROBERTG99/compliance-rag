import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { useApi } from "../../api/hooks";
import type { EvalsLatest } from "../../api/types";
import { BarChart } from "../../components/BarChart";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { fmt, lowerIsBetter, unitOf } from "./units";

type Row = Record<string, string | number>;

export function EvaluationPage() {
  const api = useApi();
  const report = useQuery({
    queryKey: ["evals-latest"],
    queryFn: ({ signal }) => api<EvalsLatest>("/v1/evals/latest", { signal }),
    retry: false,
  });
  if (report.isPending) return <Skeleton lines={6} label="Loading report" />;
  if (report.isError) {
    if (report.error instanceof ApiError && report.error.status === 404) {
      return (
        <EmptyState title="No evaluation report yet">
          Run <code>make eval</code> to produce one.
        </EmptyState>
      );
    }
    return <ErrorState error={report.error} onRetry={() => void report.refetch()} />;
  }
  const r = report.data;
  const ablation = (r.ablation ?? []) as Row[];
  const metricKeys = ablation.length
    ? Object.keys(ablation[0]).filter(
        (k) => k !== "config" && k !== "n" && typeof ablation[0][k] === "number",
      )
    : [];

  return (
    <div className="space-y-6">
      <h1 className="font-serif text-2xl font-semibold">Evaluation</h1>
      <p className="text-sm text-muted">
        {r.split} split · {r.llm} · generated {new Date(r.generated_at).toLocaleString()}
      </p>
      <table aria-label="Metrics" className="text-sm">
        <tbody>
          {Object.entries(r.metrics).map(([k, v]) => (
            <tr key={k} className="border-b border-rule">
              <th scope="row" className="py-1 pr-6 text-left font-medium">
                {k}
                {lowerIsBetter(k) ? (
                  <span className="ml-1 font-normal text-muted">(lower is better)</span>
                ) : null}
              </th>
              <td className="py-1 text-right tabular-nums">
                {typeof v === "number" ? fmt(k, v) : String(v)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {ablation.length ? (
        <section aria-label="Ablation" className="space-y-4">
          <h2 className="font-serif text-xl font-semibold">Retrieval ablation</h2>
          <div className="grid gap-6 md:grid-cols-2">
            {metricKeys.map((k) => (
              <BarChart
                key={k}
                title={`${k} by configuration${lowerIsBetter(k) ? " (lower is better)" : ""}`}
                bars={ablation.map((row) => ({ label: String(row.config), value: Number(row[k]) }))}
                max={unitOf(k) === "rate" ? 1 : undefined}
                format={(v) => fmt(k, v)}
              />
            ))}
          </div>
          <div
            tabIndex={0}
            role="region"
            aria-label="Ablation table, scrollable"
            className="overflow-x-auto"
          >
            <table aria-label="Ablation table" className="text-sm">
              <thead className="border-b border-rule text-muted">
                <tr>
                  <th scope="col" className="py-1 pr-4 text-left font-medium">
                    Configuration
                  </th>
                  {metricKeys.map((k) => (
                    <th key={k} scope="col" className="py-1 pr-4 text-right font-medium">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ablation.map((row) => (
                  <tr key={String(row.config)} className="border-b border-rule">
                    <td className="py-1 pr-4">{String(row.config)}</td>
                    {metricKeys.map((k) => (
                      <td key={k} className="py-1 pr-4 text-right tabular-nums">
                        {fmt(k, Number(row[k]))}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
