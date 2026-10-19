import { createContext, useContext } from "react";
import type { useAskRun } from "./useAskRun";

export type AskRun = ReturnType<typeof useAskRun> & {
  question: string;
  setQuestion: (value: string) => void;
  asOf: string;
  setAsOf: (value: string) => void;
};

export const AskRunContext = createContext<AskRun | null>(null);

export function useAskRunContext(): AskRun {
  const run = useContext(AskRunContext);
  if (!run) throw new Error("useAskRunContext outside <AskRunProvider>");
  return run;
}
