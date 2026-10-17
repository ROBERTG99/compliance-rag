import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mockFetch, renderApp, signInAs } from "../../test/render";

const REPORT = {
  generated_at: "2026-10-17T10:00:00Z",
  split: "test",
  llm: "FakeLLM (offline)",
  metrics: { "recall@10": 0.95, "MRR@10": 0.93, acl_leak: 0, abstention_accuracy: 0.97 },
  ablation: [
    { config: "bm25", "recall@10": 0.81, "MRR@10": 0.72, p95_ms: 40 },
    { config: "hybrid+rerank", "recall@10": 0.95, "MRR@10": 0.93, p95_ms: 110 },
  ],
};

beforeEach(() => {
  sessionStorage.clear();
  signInAs("analyst");
});
afterEach(() => vi.unstubAllGlobals());

test("the latest report shows metrics, its provenance and an ablation chart with a table view", async () => {
  mockFetch(() => ({ status: 200, body: REPORT }));
  renderApp("/evaluation");
  expect(await screen.findByText(/FakeLLM \(offline\)/)).toBeInTheDocument();
  expect(screen.getByText(/test split/i)).toBeInTheDocument();
  const metrics = screen.getByRole("table", { name: /metrics/i });
  expect(within(metrics).getByText("recall@10")).toBeInTheDocument();
  const chart = screen.getByRole("img", { name: /recall@10 by configuration/i });
  expect(chart.querySelectorAll("rect[data-value]")).toHaveLength(2);
  const table = screen.getByRole("table", { name: /ablation/i });
  expect(within(table).getByText("hybrid+rerank")).toBeInTheDocument();
});

test("no report yet is an empty state, not an error", async () => {
  mockFetch(() => ({ status: 404, body: { type: "x", title: "Not Found", status: 404 } }));
  renderApp("/evaluation");
  expect(await screen.findByText(/no evaluation report yet/i)).toBeInTheDocument();
});
