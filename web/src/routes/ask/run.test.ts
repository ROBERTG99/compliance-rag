import { expect, test } from "vitest";
import { initialRun, runReducer } from "./run";

const claim = { index: 0, text: "A verified claim.", citations: [] };

test("a failed request drops claims streamed before it, like an error event", () => {
  const running = runReducer(runReducer(initialRun, { type: "start" }), {
    type: "event",
    event: { id: 1, event: "claim", data: claim },
  });
  expect(running.claims).toHaveLength(1);
  const failed = runReducer(running, {
    type: "fail",
    error: { code: "request", message: "the request failed", retryable: true },
  });
  expect(failed.phase).toBe("error");
  expect(failed.claims).toEqual([]);
});
