import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "../../api/hooks";
import type { IndexLag, JobPage } from "../../api/types";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";

const STATUSES = [
  "queued",
  "parsing",
  "embedding",
  "indexing",
  "activating",
  "done",
  "failed",
] as const;
const KINDS = ["ingest", "acl_sync", "reindex"] as const;
const REFRESH_MS = 15_000;

const seconds = (s: number) => `${s.toFixed(1)} s`;
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { timeZoneName: "short" }) : "—";

export function JobsPage() {
  const api = useApi();
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [live, setLive] = useState(true); // WCAG 2.2.2: auto-refresh can be paused
  const lag = useQuery({
    queryKey: ["index-lag"],
    queryFn: ({ signal }) => api<IndexLag>("/v1/index/lag", { signal }),
    refetchInterval: live ? REFRESH_MS : false,
  });
  const jobs = useQuery({
    queryKey: ["jobs", status, kind],
    queryFn: ({ signal }) =>
      api<JobPage>("/v1/ingestion-jobs", { query: { status, kind, limit: 200 }, signal }),
    refetchInterval: live ? REFRESH_MS : false,
  });

  return (
    <div className="space-y-6">
      <h1 className="font-serif text-2xl font-semibold">Ingestion jobs</h1>
      <section aria-label="Index lag">
        {lag.isPending ? (
          <Skeleton lines={1} label="Loading lag" />
        ) : !lag.data ? (
          <ErrorState error={lag.error} onRetry={() => void lag.refetch()} />
        ) : (
          <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Pending" value={String(lag.data.pending)} />
            <Tile label="Oldest waiting" value={seconds(lag.data.oldest_pending_s)} />
            <Tile label="p50 (24 h)" value={seconds(lag.data.p50_s)} />
            <Tile label="p95 (24 h)" value={seconds(lag.data.p95_s)} />
          </dl>
        )}
      </section>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          <span>Refresh every 15 s</span>
        </label>
        {jobs.dataUpdatedAt ? (
          <span className="text-muted">
            Updated {new Date(jobs.dataUpdatedAt).toLocaleTimeString()}
          </span>
        ) : null}
        <label className="flex items-center gap-1">
          <span>Status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-control bg-surface placeholder:text-muted px-1 py-0.5"
          >
            <option value="">all</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span>Kind</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded border border-control bg-surface placeholder:text-muted px-1 py-0.5"
          >
            <option value="">all</option>
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
      </div>
      {jobs.data && jobs.isError ? (
        <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : null}
      {jobs.isPending ? (
        <Skeleton lines={5} label="Loading jobs" />
      ) : !jobs.data ? (
        <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : jobs.data.items.length === 0 ? (
        <EmptyState title="No jobs match these filters" />
      ) : (
        <div
          tabIndex={0}
          role="region"
          aria-label="Ingestion jobs table, scrollable"
          className="overflow-x-auto"
        >
          <table aria-label="Ingestion jobs" className="w-full text-left text-sm">
            <thead className="border-b border-rule text-muted">
              <tr>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Document
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Kind
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Status
                </th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">
                  Attempts
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Enqueued
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Finished
                </th>
                <th scope="col" className="py-1 font-medium">
                  Error
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.items.map((j) => (
                <tr key={j.job_id} className="border-b border-rule align-top">
                  <td className="py-1 pr-3">
                    {j.version ? `${j.document_id} v${j.version}` : j.document_id}
                  </td>
                  <td className="py-1 pr-3">{j.kind}</td>
                  <td className={`py-1 pr-3 ${j.status === "failed" ? "text-restricted" : ""}`}>
                    {j.status}
                  </td>
                  <td className="py-1 pr-3 text-right tabular-nums">{j.attempts}</td>
                  <td className="py-1 pr-3">{when(j.enqueued_at)}</td>
                  <td className="py-1 pr-3">{when(j.finished_at)}</td>
                  <td className="max-w-xs break-words py-1">{j.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-control bg-surface placeholder:text-muted p-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
