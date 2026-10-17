import { useState } from "react";
import { useApi } from "../../api/hooks";
import type { FeedbackRequest } from "../../api/types";
import { ErrorState } from "../../components/States";

const REASONS: { value: FeedbackRequest["reason"]; label: string }[] = [
  { value: "correct", label: "Correct" },
  { value: "wrong_fact", label: "Wrong fact" },
  { value: "wrong_citation", label: "Wrong citation" },
  { value: "outdated", label: "Outdated" },
  { value: "missing_info", label: "Missing information" },
  { value: "should_abstain", label: "Should not have answered" },
  { value: "other", label: "Other" },
];

export function Feedback({ runId }: { runId: string }) {
  const api = useApi();
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [reason, setReason] = useState<FeedbackRequest["reason"]>("correct");
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<unknown>(null);

  const choose = (value: "up" | "down") => {
    setRating(value);
    setReason(value === "up" ? "correct" : "wrong_fact");
  };

  const send = async () => {
    if (!rating) return;
    setState("sending");
    setError(null);
    try {
      const body: FeedbackRequest = {
        run_id: runId,
        rating,
        reason,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      };
      await api("/v1/feedback", { method: "POST", json: body });
      setState("sent");
    } catch (exc) {
      setError(exc);
      setState("idle");
    }
  };

  if (state === "sent")
    return <p className="text-sm text-ok">Thanks — your feedback was recorded.</p>;
  return (
    <fieldset className="rounded border border-rule p-3 text-sm">
      <legend className="px-1 font-medium">Was this answer helpful?</legend>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={rating === "up"}
          onClick={() => choose("up")}
          className="rounded border border-rule px-2 py-1 aria-pressed:bg-accent aria-pressed:text-accent-ink"
        >
          <span aria-hidden="true">👍</span> Helpful
        </button>
        <button
          type="button"
          aria-pressed={rating === "down"}
          onClick={() => choose("down")}
          className="rounded border border-rule px-2 py-1 aria-pressed:bg-accent aria-pressed:text-accent-ink"
        >
          <span aria-hidden="true">👎</span> Not helpful
        </button>
        {rating ? (
          <>
            <label className="flex items-center gap-1">
              <span>Reason</span>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as FeedbackRequest["reason"])}
                className="rounded border border-rule bg-surface px-1 py-0.5"
              >
                {REASONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-48 flex-1 items-center gap-1">
              <span className="sr-only">Comment</span>
              <input
                value={comment}
                maxLength={1000}
                placeholder="Optional comment"
                onChange={(e) => setComment(e.target.value)}
                className="w-full rounded border border-rule bg-surface px-1 py-0.5"
              />
            </label>
            <button
              type="button"
              onClick={() => void send()}
              disabled={state === "sending"}
              className="rounded bg-accent px-3 py-1 text-accent-ink"
            >
              Send feedback
            </button>
          </>
        ) : null}
      </div>
      {error ? (
        <div className="mt-2">
          <ErrorState error={error} onRetry={() => void send()} />
        </div>
      ) : null}
    </fieldset>
  );
}
