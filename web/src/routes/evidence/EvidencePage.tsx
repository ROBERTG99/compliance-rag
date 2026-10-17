import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useApi } from "../../api/hooks";
import type { ChunkOut } from "../../api/types";
import { ErrorState, Skeleton } from "../../components/States";
import { findQuote } from "./highlight";

export function EvidencePage() {
  const { chunkId = "" } = useParams();
  const [params] = useSearchParams();
  const quote = params.get("quote") ?? "";
  const api = useApi();
  const chunk = useQuery({
    queryKey: ["chunk", chunkId],
    queryFn: ({ signal }) => api<ChunkOut>(`/v1/chunks/${encodeURIComponent(chunkId)}`, { signal }),
    retry: false,
  });

  if (chunk.isPending) return <Skeleton lines={6} label="Loading evidence" />;
  if (chunk.isError) return <ErrorState error={chunk.error} onRetry={() => void chunk.refetch()} />;
  const c = chunk.data;
  // join hard-wrapped lines (single newlines) with a space: same length, so quote offsets still apply
  const text = c.text.replace(/(?<!\n)\n(?!\n)/g, " ");
  const span = quote ? findQuote(text, quote) : null;

  return (
    <article className="max-w-[72ch]">
      <p className="text-sm text-muted">Evidence</p>
      <h1 className="font-serif text-2xl font-semibold">{c.title}</h1>
      <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded border border-accent px-1.5 font-medium text-accent">
          {c.document_id} v{c.version}
        </span>
        <span>{c.section_path}</span>
        <span className="text-muted">
          valid {c.valid_from}
          {c.valid_to ? ` – ${c.valid_to}` : " onward"}
        </span>
      </p>
      {c.superseded ? (
        <div
          role="note"
          aria-label="Superseded version"
          className="mt-3 rounded border border-restricted p-3 text-sm"
        >
          <p>
            This version is superseded: valid until {c.valid_to}.{" "}
            <Link to={`/library/${c.document_id}`} className="font-medium underline">
              Current version v{c.current_version}
            </Link>
          </p>
        </div>
      ) : null}
      <div className="mt-4 whitespace-pre-line font-serif text-lg leading-relaxed">
        {span ? (
          <>
            {text.slice(0, span[0])}
            <mark className="rounded bg-highlight px-0.5 text-ink">
              {text.slice(span[0], span[1])}
            </mark>
            {text.slice(span[1])}
          </>
        ) : (
          text
        )}
      </div>
      {quote && !span ? (
        <p className="mt-3 text-sm text-muted">
          The quoted passage could not be located in this excerpt.
        </p>
      ) : null}
    </article>
  );
}
