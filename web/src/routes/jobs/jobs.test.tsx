import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mockFetch, renderApp, signInAs } from "../../test/render";

const JOBS = {
  items: [
    {
      job_id: "j1",
      kind: "ingest",
      document_id: "AML-0107",
      version: 4,
      status: "queued",
      attempts: 0,
      error: null,
      requested_by: "admin@northwind.test",
      enqueued_at: "2026-10-16T10:00:00+00:00",
      finished_at: null,
      chunk_count: null,
    },
    {
      job_id: "j2",
      kind: "acl_sync",
      document_id: "KYC-0042",
      version: null,
      status: "indexing",
      attempts: 3,
      error: "ConnectError: opensearch down",
      requested_by: "admin@northwind.test",
      enqueued_at: "2026-10-16T09:00:00+00:00",
      finished_at: null,
      chunk_count: null,
    },
  ],
};

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test("the jobs screen shows pending lag, statuses, attempts and errors", async () => {
  signInAs("admin");
  const calls = mockFetch((url) => {
    if (url === "/v1/index/lag")
      return { status: 200, body: { p50_s: 1.2, p95_s: 4.5, pending: 3, oldest_pending_s: 42 } };
    if (url.startsWith("/v1/ingestion-jobs")) return { status: 200, body: JOBS };
    return { status: 404, body: {} };
  });
  renderApp("/jobs");
  const lag = await screen.findByRole("region", { name: /index lag/i });
  expect(await within(lag).findByText("3")).toBeInTheDocument();
  expect(within(lag).getByText(/pending/i)).toBeInTheDocument();
  expect(within(lag).getByText("4.5 s")).toBeInTheDocument();
  const table = await screen.findByRole("table", { name: /ingestion jobs/i });
  expect(within(table).getByText("AML-0107 v4")).toBeInTheDocument();
  expect(within(table).getByText(/opensearch down/)).toBeInTheDocument();

  await userEvent.setup().selectOptions(screen.getByLabelText(/status/i), "failed");
  await screen.findByRole("table", { name: /ingestion jobs/i });
  expect(calls.some((c) => c.url.includes("status=failed"))).toBe(true);
});

test("an empty job list shows the empty state", async () => {
  signInAs("admin");
  mockFetch((url) =>
    url === "/v1/index/lag"
      ? { status: 200, body: { p50_s: 0, p95_s: 0, pending: 0, oldest_pending_s: 0 } }
      : { status: 200, body: { items: [] } },
  );
  renderApp("/jobs");
  expect(await screen.findByText(/no jobs/i)).toBeInTheDocument();
});
