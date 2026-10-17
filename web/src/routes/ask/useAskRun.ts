import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useApi } from "../../api/hooks";
import { streamRun } from "../../api/sse";
import type { AskAccepted } from "../../api/types";
import { useAuth } from "../../auth/context";
import { initialRun, runReducer } from "./run";

export interface AskInput {
  question: string;
  asOf: string;
}

export function useAskRun() {
  const api = useApi();
  const { token } = useAuth();
  const [state, dispatch] = useReducer(runReducer, initialRun);
  const [requestError, setRequestError] = useState<unknown>(null);
  const last = useRef<AskInput | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const ask = useCallback(
    async (input: AskInput) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      last.current = input;
      setRequestError(null);
      dispatch({ type: "start" });
      try {
        const accepted = await api<AskAccepted>("/v1/ask", {
          method: "POST",
          json: { question: input.question, as_of: input.asOf || undefined, stream: true },
          signal: controller.signal,
        });
        await streamRun(accepted.events_url, token, (event) => dispatch({ type: "event", event }), {
          signal: controller.signal,
        });
      } catch (exc) {
        if ((exc as Error).name === "AbortError") return;
        setRequestError(exc);
        const message = exc instanceof ApiError ? exc.message : "the request failed";
        // only offer Retry when it can help: never for a 400/404/422
        const retryable = exc instanceof ApiError ? exc.retryable : true;
        dispatch({ type: "fail", error: { code: "request", message, retryable } });
      }
    },
    [api, token],
  );

  const retry = useCallback(() => {
    if (last.current) void ask(last.current);
  }, [ask]);

  return { state, requestError, ask, retry };
}
