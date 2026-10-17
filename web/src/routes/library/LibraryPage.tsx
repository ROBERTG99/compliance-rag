import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../../api/hooks";
import type { DocumentPage } from "../../api/types";
import { useAuth } from "../../auth/context";
import { isAdmin } from "../../auth/session";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";

const DOMAINS = ["aml", "complaints", "kyc", "limits", "retention", "vendors"] as const;

export function LibraryPage() {
  const api = useApi();
  const { principal } = useAuth();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState(""); // what is sent: debounced so typing does not fire a request per key
  useEffect(() => {
    const timer = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(timer);
  }, [q]);
  const [domain, setDomain] = useState("");
  const [validAt, setValidAt] = useState("");
  const docs = useInfiniteQuery({
    queryKey: ["documents", query, domain, validAt],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) =>
      api<DocumentPage>("/v1/documents", {
        query: { q: query, domain, valid_at: validAt, cursor: pageParam, limit: 50 },
        signal,
      }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = docs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <h1 className="font-serif text-2xl font-semibold">Document library</h1>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-1">
          <span>Search</span>
          <input
            value={q}
            maxLength={200}
            onChange={(e) => setQ(e.target.value)}
            className="rounded border border-control bg-surface placeholder:text-muted px-1 py-0.5"
          />
        </label>
        <label className="flex items-center gap-1">
          <span>Domain</span>
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="rounded border border-control bg-surface placeholder:text-muted px-1 py-0.5"
          >
            <option value="">all</option>
            {DOMAINS.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span>Valid at</span>
          <input
            type="date"
            value={validAt}
            onChange={(e) => setValidAt(e.target.value)}
            className="rounded border border-control bg-surface placeholder:text-muted px-1 py-0.5"
          />
        </label>
      </div>
      {docs.isPending ? (
        <Skeleton lines={6} label="Loading documents" />
      ) : docs.isError ? (
        <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title="No documents match these filters" />
      ) : (
        <>
          <ul aria-label="Documents" className="divide-y divide-rule">
            {items.map((d) => (
              <li key={d.document_id} className="flex flex-wrap items-baseline gap-x-3 py-2">
                <Link to={`/library/${d.document_id}`} className="font-medium underline">
                  {d.document_id}
                </Link>
                <span className="font-serif">{d.title}</span>
                <span className="text-sm text-muted">
                  {d.domain} ·{" "}
                  {d.current_version ? `v${d.current_version} in force` : "no version in force"} ·{" "}
                  {d.versions} version
                  {d.versions === 1 ? "" : "s"}
                </span>
                {isAdmin(principal) && d.restricted ? (
                  <span className="rounded border border-restricted px-1.5 text-sm text-restricted">
                    Restricted · {(d.acl_groups ?? []).join(", ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          {docs.hasNextPage ? (
            <button
              type="button"
              onClick={() => void docs.fetchNextPage()}
              disabled={docs.isFetchingNextPage}
              className="rounded border border-control px-3 py-1 text-sm"
            >
              Load more
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
