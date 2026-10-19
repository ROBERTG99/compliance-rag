import { ApiError } from "./client";
import type { Problem } from "./types";

export interface RunEvent {
  id: number;
  event: string;
  // event payloads follow BUILD.md §4.5; screens narrow them by `event`
  data: Record<string, unknown>;
}

export const TERMINAL = new Set(["final", "error"]);
const RETRY_STATUS = new Set([502, 503, 504]); // the API restarting or a proxy blip: Redis still holds the replay

/** Parse complete SSE blocks out of `buffer`; returns the events and the unconsumed tail. */
export function parseSse(buffer: string): { events: RunEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: RunEvent[] = [];
  for (const block of blocks) {
    let id: number | null = null;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue; // comments are keep-alive pings
      const sep = line.indexOf(":");
      const field = sep < 0 ? line : line.slice(0, sep);
      const value = sep < 0 ? "" : line.slice(sep + 1).replace(/^ /, "");
      if (field === "id") id = Number(value);
      else if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (id === null || data.length === 0) continue;
    try {
      events.push({ id, event, data: JSON.parse(data.join("\n")) as Record<string, unknown> });
    } catch {
      /* a malformed block is skipped (resume continues from the last event that parsed) */
    }
  }
  return { events, rest };
}

export interface StreamOptions {
  signal?: AbortSignal;
  lastEventId?: number;
  maxRetries?: number;
  retryDelayMs?: number;
}

/**
 * Follow a run's event stream until a terminal event, resuming with `Last-Event-ID` after a dropped
 * connection (the API replays from Redis Streams). Returns the last event id seen.
 */
export async function streamRun(
  url: string,
  token: string | null,
  onEvent: (event: RunEvent) => void,
  opts: StreamOptions = {},
): Promise<number> {
  let lastId = opts.lastEventId ?? 0;
  const maxRetries = opts.maxRetries ?? 3;
  let attempt = 0;
  for (;;) {
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (lastId > 0) headers["Last-Event-ID"] = String(lastId);
    let done = false;
    try {
      const resp = await fetch(url, { headers, signal: opts.signal });
      if (!resp.ok) {
        const problem = (await resp.json().catch(() => null)) as Problem | null;
        throw new ApiError(resp.status, problem);
      }
      if (!resp.body) throw new ApiError(0, null);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done: eof } = await reader.read();
        if (eof) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSse(buffer);
        buffer = parsed.rest;
        for (const event of parsed.events) {
          if (event.id <= lastId) continue; // replayed duplicates after a resume
          lastId = event.id;
          attempt = 0; // progress: a long run may drop several times without failing
          onEvent(event);
          if (TERMINAL.has(event.event)) done = true;
        }
        if (done) {
          await reader.cancel().catch(() => undefined);
          break;
        }
      }
    } catch (exc) {
      if ((exc as Error).name === "AbortError") throw exc;
      if (exc instanceof ApiError && exc.status !== 0 && !RETRY_STATUS.has(exc.status)) throw exc; // 404 etc. are final
      if (attempt >= maxRetries) throw exc instanceof ApiError ? exc : new ApiError(0, null);
    }
    if (done) return lastId;
    if (attempt >= maxRetries) throw new ApiError(0, null);
    attempt += 1;
    await new Promise((r) => setTimeout(r, (opts.retryDelayMs ?? 500) * attempt));
  }
}
