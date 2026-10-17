import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mockFetch, renderApp, signInAs } from "../../test/render";

const ITEM = {
  id: "f1",
  run_id: "r1",
  rating: "down",
  reason: "wrong_fact",
  comment: "says 90, policy says 60",
  status: "new",
  created_at: "2026-10-17T09:00:00Z",
  user_sub: "analyst@northwind.test",
  question: "What is the maximum age of a proof-of-address document?",
  as_of: "2026-10-17",
  abstained: false,
  in_test_split: false,
};

beforeEach(() => {
  sessionStorage.clear();
  signInAs("admin");
});
afterEach(() => vi.unstubAllGlobals());

test("an admin triages feedback into the dev set; test-split questions cannot be added", async () => {
  const calls = mockFetch((url, init) => {
    if (url.startsWith("/v1/feedback?") || url === "/v1/feedback") {
      return {
        status: 200,
        body: {
          items: [ITEM, { ...ITEM, id: "f2", in_test_split: true, question: "A test question?" }],
          next_cursor: null,
        },
      };
    }
    if (url === "/v1/feedback/f1" && init?.method === "PATCH") {
      return { status: 200, body: { ...ITEM, status: JSON.parse(String(init.body)).status } };
    }
    return { status: 404, body: {} };
  });
  renderApp("/feedback");
  const rows = await screen.findAllByRole("article");
  const first = rows[0];
  expect(within(first).getByText(/says 90, policy says 60/)).toBeInTheDocument();
  await userEvent.setup().click(within(first).getByRole("button", { name: /add to dev set/i }));
  await waitFor(() =>
    expect(calls.some((c) => c.url === "/v1/feedback/f1" && c.init?.method === "PATCH")).toBe(true),
  );
  const patch = calls.find((c) => c.init?.method === "PATCH");
  expect(JSON.parse(String(patch?.init?.body))).toEqual({
    status: "added_to_dev_set",
    split: "dev",
  });
  const second = rows[1];
  expect(within(second).getByRole("button", { name: /add to dev set/i })).toBeDisabled();
  expect(within(second).getByText(/held-out test split/i)).toBeInTheDocument();
});

test("retry re-sends a triage that failed, and success is announced", async () => {
  let patches = 0;
  mockFetch((_url, init) => {
    if (init?.method === "PATCH") {
      patches += 1;
      return patches === 1
        ? { status: 503, body: { type: "x", title: "Service Unavailable", status: 503 } }
        : { status: 200, body: { ...ITEM, status: "triaged" } };
    }
    return { status: 200, body: { items: [ITEM], next_cursor: null } };
  });
  renderApp("/feedback");
  const user = userEvent.setup();
  const [card] = await screen.findAllByRole("article");
  await user.click(within(card).getByRole("button", { name: /mark triaged/i }));
  await user.click(await screen.findByRole("button", { name: /retry/i }));
  await waitFor(() => expect(patches).toBe(2));
  expect(await screen.findByText("Marked as triaged.")).toBeInTheDocument();
});
