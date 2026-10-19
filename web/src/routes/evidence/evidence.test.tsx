import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mockFetch, renderApp, signInAs } from "../../test/render";
import { findQuote } from "./highlight";

const CHUNK = {
  chunk_id: "a".repeat(32),
  document_id: "KYC-0042",
  version: 2,
  section_path: "Article 4 — Acceptable Proof of Address",
  text: "Article 4.\nA proof-of-address document must not be older than\n120 days at the date of onboarding. Copies are kept.",
  char_start: 100,
  char_end: 210,
  valid_from: "2025-01-01",
  valid_to: "2026-03-01",
  title: "Proof of Address",
  current_version: 3,
  superseded: true,
};

beforeEach(() => {
  sessionStorage.clear();
  signInAs("analyst");
});
afterEach(() => vi.unstubAllGlobals());

test("findQuote tolerates line breaks and spacing differences", () => {
  const [start, end] = findQuote(CHUNK.text, "must not be older than 120 days")!;
  expect(CHUNK.text.slice(start, end)).toBe("must not be older than\n120 days");
  expect(findQuote(CHUNK.text, "not in the text")).toBeNull();
});

test("the quote is highlighted and a superseded version links to the current one", async () => {
  mockFetch((url) =>
    url === `/v1/chunks/${CHUNK.chunk_id}`
      ? { status: 200, body: CHUNK }
      : { status: 404, body: {} },
  );
  renderApp(
    `/evidence/${CHUNK.chunk_id}?quote=${encodeURIComponent("must not be older than 120 days")}`,
  );
  const mark = await screen.findByText(/must not be older than/, { selector: "mark" });
  expect(mark.textContent?.replace(/\s+/g, " ")).toBe("must not be older than 120 days");
  expect(screen.getByText("KYC-0042 v2")).toBeInTheDocument();
  const warning = screen.getByRole("note", { name: /superseded/i });
  expect(warning).toHaveTextContent(/valid until 2026-03-01/i);
  const current = screen.getByRole("link", { name: /current version v3/i });
  expect(current).toHaveAttribute("href", "/library/KYC-0042");
});

test("a chunk the user may not see is a plain not-found (retrying cannot help)", async () => {
  mockFetch(() => ({
    status: 404,
    body: { type: "x", title: "Not Found", status: 404, detail: "chunk not found" },
  }));
  renderApp(`/evidence/${"b".repeat(32)}`);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(/chunk not found/i);
  expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
});

test("a transient failure offers retry", async () => {
  let calls = 0;
  mockFetch(() => {
    calls += 1;
    return { status: 503, body: { type: "x", title: "Service Unavailable", status: 503 } };
  });
  renderApp(`/evidence/${"b".repeat(32)}`);
  await screen.findByRole("alert");
  await userEvent.setup().click(screen.getByRole("button", { name: /retry/i }));
  expect(calls).toBeGreaterThanOrEqual(2);
});
