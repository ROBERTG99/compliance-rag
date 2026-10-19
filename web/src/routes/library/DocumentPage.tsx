import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../../api/hooks";
import type { DocumentDetail, VersionEntry } from "../../api/types";
import { ErrorState, Skeleton } from "../../components/States";
import { today } from "../../lib/dates";

function versionState(v: VersionEntry, day: string): { label: string; tone: string } {
  if (v.status !== "active") return { label: v.status, tone: "text-muted" };
  if (v.in_force) return { label: "In force", tone: "text-ok" };
  if (v.valid_from > day) return { label: "Announced", tone: "text-muted" }; // not yet in force
  return { label: "Superseded", tone: "text-muted" }; // restricted red is reserved for access control
}

export function DocumentPage() {
  const { documentId = "" } = useParams();
  const api = useApi();
  const doc = useQuery({
    queryKey: ["document", documentId],
    queryFn: ({ signal }) =>
      api<DocumentDetail>(`/v1/documents/${encodeURIComponent(documentId)}`, { signal }),
    retry: false,
  });
  const title = doc.data?.title;
  useEffect(() => {
    if (title) document.title = `${documentId} ${title} · Northwind Compliance Assistant`;
  }, [documentId, title]);
  if (doc.isPending) return <Skeleton lines={5} label="Loading document" />;
  if (doc.isError) return <ErrorState error={doc.error} onRetry={() => void doc.refetch()} />;
  const d = doc.data;
  return (
    <article className="max-w-3xl space-y-4">
      <p className="text-sm">
        <Link to="/library" className="underline">
          Library
        </Link>{" "}
        / {d.document_id}
      </p>
      <h1 className="font-serif text-2xl font-semibold">{d.title}</h1>
      <p className="text-sm text-muted">
        {d.domain} · owner {d.owner}
        {d.acl_groups ? ` · shared with ${d.acl_groups.join(", ")}` : ""}
      </p>
      <ol aria-label="Versions" className="border-l-2 border-rule pl-4">
        {d.versions.map((v) => {
          const state = versionState(v, today());
          return (
            <li key={v.version} className="relative py-2">
              <span
                className="absolute -left-[1.4rem] top-3.5 h-2.5 w-2.5 rounded-full bg-accent"
                aria-hidden="true"
              />
              <span className="font-medium">v{v.version}</span> · valid {v.valid_from}
              {v.valid_to ? ` – ${v.valid_to}` : " onward"} ·{" "}
              <span className={`font-medium ${state.tone}`}>{state.label}</span>
              <span className="text-sm text-muted">
                {" "}
                · {v.chunks} chunks · {v.source_format}
              </span>
            </li>
          );
        })}
      </ol>
    </article>
  );
}
