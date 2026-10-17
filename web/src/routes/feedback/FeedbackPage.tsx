import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useApi } from "../../api/hooks";
import type { FeedbackPage as Page, TriageItem, TriageRequest } from "../../api/types";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";

export function FeedbackPage() {
  const api = useApi();
  const client = useQueryClient();
  const [status, setStatus] = useState("new");
  const [rating, setRating] = useState("");
  const list = useQuery({
    queryKey: ["feedback", status, rating],
    queryFn: ({ signal }) =>
      api<Page>("/v1/feedback", { query: { status, rating, limit: 100 }, signal }),
  });
  const [announcement, setAnnouncement] = useState("");
  const statusLine = useRef<HTMLParagraphElement>(null);
  type Triage = { id: string; question: string; body: TriageRequest };
  const [lastTriage, setLastTriage] = useState<Triage | null>(null);
  const triage = useMutation({
    mutationFn: ({ id, body }: Triage) =>
      api(`/v1/feedback/${id}`, { method: "PATCH", json: body }),
    onMutate: () => setAnnouncement(""),
    onSuccess: (_data, { body, question }) => {
      // name the item, so a second identical action is announced too
      setAnnouncement(
        `${body.status === "added_to_dev_set" ? "Added to the dev set" : "Marked as triaged"}: “${question}”`,
      );
      // the card (and its focused button) may leave the filtered list: keep focus on the outcome
      statusLine.current?.focus();
      void client.invalidateQueries({ queryKey: ["feedback"] });
    },
  });

  // Retry re-sends the request that failed (not just dismissing the error)
  const retryTriage = () => (lastTriage ? triage.mutate(lastTriage) : triage.reset());

  return (
    <div className="space-y-4">
      <h1 className="font-serif text-2xl font-semibold">Feedback review</h1>
      <p className="max-w-prose text-sm text-muted">
        Triaged answers can be added to the dev split for tuning. Questions from the held-out test
        split cannot.
      </p>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-1">
          <span>Status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-control bg-surface px-1 py-0.5"
          >
            <option value="">all</option>
            <option value="new">new</option>
            <option value="triaged">triaged</option>
            <option value="added_to_dev_set">added to dev set</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span>Rating</span>
          <select
            value={rating}
            onChange={(e) => setRating(e.target.value)}
            className="rounded border border-control bg-surface px-1 py-0.5"
          >
            <option value="">all</option>
            <option value="up">helpful</option>
            <option value="down">not helpful</option>
          </select>
        </label>
      </div>
      <p
        ref={statusLine}
        tabIndex={-1}
        role="status"
        className="text-sm text-ok focus:outline-none"
      >
        {announcement}
      </p>
      {triage.isError ? (
        <ErrorState error={triage.error} onRetry={retryTriage} onDismiss={() => triage.reset()} />
      ) : null}
      {list.isPending ? (
        <Skeleton lines={6} label="Loading feedback" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.items.length === 0 ? (
        <EmptyState title="No feedback matches these filters" />
      ) : (
        <div className="space-y-3">
          {list.data.items.map((item) => (
            <FeedbackCard
              key={item.id}
              item={item}
              busy={triage.isPending}
              onTriage={(body) => {
                const next = { id: item.id, question: item.question, body };
                setLastTriage(next);
                triage.mutate(next);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FeedbackCard({
  item,
  busy,
  onTriage,
}: {
  item: TriageItem;
  busy: boolean;
  onTriage: (body: TriageRequest) => void;
}) {
  return (
    <article
      aria-label={`Feedback on: ${item.question}`}
      className="rounded border border-control bg-surface p-3 text-sm"
    >
      <p className="font-serif text-base">{item.question}</p>
      <p className="mt-1 text-muted">
        {item.rating === "up" ? "Helpful" : "Not helpful"} · {item.reason.replace(/_/g, " ")} ·{" "}
        {item.user_sub} ·{" "}
        <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time> · as of{" "}
        {item.as_of}
        {item.abstained ? " · abstained" : ""} · {item.status.replace(/_/g, " ")}
      </p>
      {item.comment ? (
        <blockquote className="mt-2 border-l-2 border-rule pl-2">{item.comment}</blockquote>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy || item.status !== "new"}
          onClick={() => onTriage({ status: "triaged", split: "dev" })}
          className="rounded border border-control px-2 py-1 disabled:opacity-50"
        >
          Mark triaged
        </button>
        <button
          type="button"
          disabled={busy || item.in_test_split || item.status === "added_to_dev_set"}
          aria-describedby={item.in_test_split ? `split-${item.id}` : undefined}
          onClick={() => onTriage({ status: "added_to_dev_set", split: "dev" })}
          className="rounded bg-accent px-2 py-1 text-accent-ink disabled:opacity-50"
        >
          Add to dev set
        </button>
        {item.in_test_split ? (
          <span id={`split-${item.id}`} className="text-restricted">
            This question is in the held-out test split.
          </span>
        ) : null}
      </div>
    </article>
  );
}
