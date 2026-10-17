import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Skeleton({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-2 py-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-4" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-rule p-6 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted">{children}</div> : null}
    </div>
  );
}

/** problem+json error with an explicit retry (BUILD.md §13: every screen has this state). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const title =
    api?.problem?.title ??
    (api?.status === 0 ? "Cannot reach the service" : "Something went wrong");
  const detail = api?.problem?.detail ?? (error instanceof Error ? error.message : undefined);
  return (
    <div role="alert" className="rounded border border-restricted p-4">
      <p className="font-medium text-restricted">{title}</p>
      {detail && detail !== title ? <p className="mt-1 text-sm">{detail}</p> : null}
      {api?.retryAfterS ? (
        <p className="mt-1 text-sm text-muted">Try again in {api.retryAfterS} s.</p>
      ) : null}
      {onRetry && (!api || api.retryable) ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-control px-3 py-1 text-sm"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
