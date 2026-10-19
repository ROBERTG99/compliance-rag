import { afterEach, expect, test, vi } from "vitest";
import { parseSse, streamRun, type RunEvent } from "./sse";

afterEach(() => vi.unstubAllGlobals());

const block = (id: number, event: string, data: unknown) =>
  `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

test("parseSse keeps an incomplete block for the next chunk and skips pings", () => {
  const { events, rest } = parseSse(
    `: ping\n\n${block(1, "run_started", { run_id: "r" })}id: 2\nevent: no`,
  );
  expect(events).toEqual([{ id: 1, event: "run_started", data: { run_id: "r" } }]);
  expect(rest).toBe("id: 2\nevent: no");
});

function streamOf(text: string, cut = false): Response {
  let sent = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (!sent) {
        sent = true;
        controller.enqueue(new TextEncoder().encode(text));
      } else if (cut) {
        controller.error(new TypeError("network error")); // dropped after the data was read
      } else {
        controller.close();
      }
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

test("streamRun resumes with Last-Event-ID after a dropped connection and ignores replayed events", async () => {
  const seen: string[] = [];
  const headers: (string | null)[] = [];
  const responses = [
    streamOf(block(1, "run_started", {}) + block(2, "node", {}), true),
    streamOf(block(2, "node", {}) + block(3, "claim", {}) + block(4, "final", {})),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      headers.push(new Headers(init.headers).get("Last-Event-ID"));
      return responses.shift()!;
    }),
  );
  const last = await streamRun(
    "/v1/runs/r/events",
    "t",
    (e: RunEvent) => seen.push(`${e.id}:${e.event}`),
    {
      retryDelayMs: 1,
    },
  );
  expect(seen).toEqual(["1:run_started", "2:node", "3:claim", "4:final"]);
  expect(headers).toEqual([null, "2"]);
  expect(last).toBe(4);
});

test("streamRun does not retry a 404", async () => {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify({ title: "Not Found", status: 404 }), { status: 404 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    streamRun("/v1/runs/x/events", "t", () => undefined, { retryDelayMs: 1 }),
  ).rejects.toMatchObject({
    status: 404,
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("streamRun retries a 503 while the API restarts and resumes from the last event", async () => {
  const seen: number[] = [];
  const responses = [
    streamOf(block(1, "run_started", {}), true),
    new Response(JSON.stringify({ title: "Service Unavailable", status: 503 }), { status: 503 }),
    streamOf(block(2, "final", {})),
  ];
  const headers: (string | null)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      headers.push(new Headers(init.headers).get("Last-Event-ID"));
      return responses.shift()!;
    }),
  );
  await streamRun("/v1/runs/r/events", "t", (e: RunEvent) => seen.push(e.id), { retryDelayMs: 1 });
  expect(seen).toEqual([1, 2]);
  expect(headers).toEqual([null, "1", "1"]);
});
