import type { Problem } from "./types";

/** An RFC 9457 problem (or a network failure, status 0) surfaced to the screens. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;
  readonly retryAfterS: number | null;

  constructor(status: number, problem: Problem | null, retryAfterS: number | null = null) {
    super(problem?.detail ?? problem?.title ?? (status ? `HTTP ${status}` : "network error"));
    this.status = status;
    this.problem = problem;
    this.retryAfterS = retryAfterS;
  }

  get retryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

export interface RequestOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export function withQuery(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query))
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function apiFetch<T>(
  path: string,
  token: string | null,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  let resp: Response;
  try {
    resp = await fetch(withQuery(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body,
      signal: opts.signal,
    });
  } catch (exc) {
    if ((exc as Error).name === "AbortError") throw exc;
    throw new ApiError(0, null);
  }
  if (!resp.ok) {
    const problem = (await resp.json().catch(() => null)) as Problem | null;
    const retry = Number(resp.headers.get("Retry-After"));
    throw new ApiError(resp.status, problem, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  return (resp.status === 204 ? undefined : await resp.json()) as T;
}
