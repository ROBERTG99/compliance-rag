import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import type { AnswerResponse, Claim } from "../../api/types";
import { useAuth } from "../../auth/context";
import { isAdmin } from "../../auth/session";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { today } from "../../lib/dates";
import { Feedback } from "./Feedback";
import type { RunState } from "./run";
import { useAskRunContext } from "./context";

const NODE_LABELS: Record<string, string> = {
  resolve_principal: "access",
  condense_followup: "follow-up",
  retrieve: "retrieve",
  fuse: "fuse",
  rerank: "rerank",
  guard_context: "guard",
  check_sufficiency: "sufficiency",
  generate: "compose",
  verify_citations: "verify",
  respond: "respond",
  abstain: "abstain",
};

export function AskPage() {
  const { principal } = useAuth();
  const { state, requestError, ask, retry, question, setQuestion, asOf, setAsOf } =
    useAskRunContext();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim()) void ask({ question: question.trim(), asOf });
  };

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_18rem]">
      <section className="min-w-0">
        <h1 className="font-serif text-2xl font-semibold">Ask a policy question</h1>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <label className="block">
            <span className="text-sm font-medium">Question</span>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={2000}
              rows={3}
              required
              className="mt-1 block w-full rounded border border-control bg-surface placeholder:text-muted p-2"
            />
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="text-sm font-medium">As of</span>
              <input
                type="date"
                value={asOf}
                max={isAdmin(principal) ? undefined : today()}
                onChange={(e) => setAsOf(e.target.value)}
                className="mt-1 block rounded border border-control bg-surface placeholder:text-muted p-1.5"
              />
            </label>
            <button
              type="submit"
              disabled={state.phase === "running"}
              className="rounded bg-accent px-4 py-2 text-accent-ink disabled:opacity-60"
            >
              Ask
            </button>
          </div>
        </form>
        <div className="mt-6">
          <RunView state={state} requestError={requestError} onRetry={retry} />
        </div>
      </section>
      <aside aria-label="Progress" className="text-sm">
        <NodeProgress state={state} />
      </aside>
    </div>
  );
}

function RunView({
  state,
  requestError,
  onRetry,
}: {
  state: RunState;
  requestError: unknown;
  onRetry: () => void;
}) {
  if (state.phase === "idle") {
    return (
      <EmptyState title="No question yet">
        Answers quote the policy versions in force on the chosen date and cite each claim.
      </EmptyState>
    );
  }
  const final = state.final;
  return (
    <div className="space-y-4">
      {state.phase === "error" ? (
        <ErrorState
          error={
            requestError instanceof ApiError
              ? requestError
              : new Error(state.error?.message ?? "Failed")
          }
          onRetry={state.error?.retryable === false ? undefined : onRetry}
        />
      ) : null}
      {/* present from the start of the run so the abstention text is announced when it arrives */}
      <div
        role="status"
        aria-label="No answer"
        className={final?.abstained ? "rounded border border-rule bg-surface p-4" : "sr-only"}
      >
        {final?.abstained ? final.message : ""}
      </div>
      {state.phase === "running" && state.claims.length === 0 ? (
        <Skeleton lines={3} label="Composing answer" />
      ) : null}
      {state.claims.length > 0 ? (
        <p className="text-sm">
          <span className="rounded bg-highlight px-1.5">AI-generated</span>{" "}
          <span className="text-muted">Each claim is checked against the quoted policy text.</span>
        </p>
      ) : null}
      <section aria-label="Answer" aria-live="polite" className="space-y-3">
        {state.claims.map((claim) => (
          <ClaimView key={claim.index} claim={claim} />
        ))}
      </section>
      {final && !final.abstained ? <AnswerMeta final={final} /> : null}
      {final ? <Feedback runId={final.run_id} /> : null}
    </div>
  );
}

function ClaimView({ claim }: { claim: Claim }) {
  return (
    <p className="font-serif text-lg leading-relaxed">
      {claim.text}{" "}
      {claim.citations.map((c) => (
        <Link
          key={c.n}
          to={`/evidence/${c.chunk_id}?quote=${encodeURIComponent(c.quote)}`}
          aria-label={`[${c.n}] citation: ${c.document_id} v${c.version}`}
          className="mx-1 inline-flex min-h-6 min-w-6 items-center justify-center rounded border border-accent px-1 font-sans text-sm text-accent no-underline"
        >
          [{c.n}]
        </Link>
      ))}
    </p>
  );
}

function AnswerMeta({ final }: { final: AnswerResponse }) {
  return (
    <div className="space-y-2 border-t border-rule pt-3 text-sm">
      <p className="flex flex-wrap gap-x-4 gap-y-1">
        <span>As of {final.as_of}</span>
        {final.confidence !== null ? <span>Confidence {final.confidence.toFixed(2)}</span> : null}
        {final.degraded.length ? (
          <span className="text-restricted">Degraded: {final.degraded.join(", ")}</span>
        ) : null}
      </p>
      <ul aria-label="Cited versions" className="space-y-1">
        {final.versions.map((v) => (
          <li key={`${v.document_id}-${v.version}`}>
            <span className="font-medium">
              {v.document_id} v{v.version}
            </span>{" "}
            {v.title} · valid {v.valid_from}
            {v.valid_to ? ` – ${v.valid_to}` : " onward"}
            {v.superseded ? (
              <span className="ml-2 font-medium text-restricted">superseded</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NodeProgress({ state }: { state: RunState }) {
  if (!state.nodes.length) return null;
  return (
    <>
      <h2 className="font-medium">Pipeline</h2>
      <ol className="mt-2 space-y-1">
        {state.nodes.map((n) => (
          <li key={n.name} className="flex justify-between gap-2">
            <span>{NODE_LABELS[n.name] ?? n.name}</span>
            <span className={n.status === "error" ? "text-restricted" : "text-muted"}>
              {n.status === "finished" ? `${Math.round(n.latencyMs)} ms` : n.status}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
