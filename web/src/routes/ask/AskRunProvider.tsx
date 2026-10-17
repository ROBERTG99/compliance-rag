import { useState, type ReactNode } from "react";
import { today } from "../../lib/dates";
import { AskRunContext } from "./context";
import { useAskRun } from "./useAskRun";

/** Keeps the current run (and the form) alive across routes, so opening the evidence and coming back keeps the answer. */
export function AskRunProvider({ children }: { children: ReactNode }) {
  const run = useAskRun();
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState(today);
  return (
    <AskRunContext.Provider value={{ ...run, question, setQuestion, asOf, setAsOf }}>
      {children}
    </AskRunContext.Provider>
  );
}
