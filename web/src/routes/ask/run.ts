import type { AnswerResponse, Claim } from "../../api/types";
import type { RunEvent } from "../../api/sse";

export type NodeStatus = "started" | "finished" | "skipped" | "error";

export interface RunError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface RunState {
  phase: "idle" | "running" | "done" | "error";
  runId: string | null;
  nodes: { name: string; status: NodeStatus; latencyMs: number }[];
  claims: Claim[];
  final: AnswerResponse | null;
  error: RunError | null;
  degraded: string[];
}

export const initialRun: RunState = {
  phase: "idle",
  runId: null,
  nodes: [],
  claims: [],
  final: null,
  error: null,
  degraded: [],
};

export type RunAction =
  { type: "start" } | { type: "event"; event: RunEvent } | { type: "fail"; error: RunError };

/** Pure reducer over §4.5 events. Only verified `claim` events add text; `token` events are not rendered. */
export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "start":
      return { ...initialRun, phase: "running" };
    case "fail":
      return { ...state, phase: "error", error: action.error };
    case "event":
      return applyEvent(state, action.event);
  }
}

function applyEvent(state: RunState, { event, data }: RunEvent): RunState {
  switch (event) {
    case "run_started":
      return { ...state, runId: String(data.run_id ?? "") };
    case "node": {
      const name = String(data.node);
      const node = {
        name,
        status: data.status as NodeStatus,
        latencyMs: Number(data.latency_ms ?? 0),
      };
      const exists = state.nodes.some((n) => n.name === name);
      return {
        ...state,
        nodes: exists
          ? state.nodes.map((n) => (n.name === name ? node : n))
          : [...state.nodes, node],
      };
    }
    case "retrieval":
      return {
        ...state,
        degraded: Array.isArray(data.degraded) ? (data.degraded as string[]) : [],
      };
    case "claim": {
      const claim = data as unknown as Claim;
      return { ...state, claims: [...state.claims.filter((c) => c.index !== claim.index), claim] };
    }
    case "claim_rejected":
      // "retracted" removes a claim that was already streamed (by its streamed index)
      return data.reason === "retracted"
        ? { ...state, claims: state.claims.filter((c) => c.index !== Number(data.index)) }
        : state;
    case "final": {
      const final = data as unknown as AnswerResponse;
      return { ...state, phase: "done", final, claims: final.claims, runId: final.run_id };
    }
    case "error":
      return {
        ...state,
        phase: "error",
        error: {
          code: String(data.code),
          message: String(data.message),
          retryable: Boolean(data.retryable),
        },
      };
    default:
      return state;
  }
}
