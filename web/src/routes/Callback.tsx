import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/context";
import { Skeleton } from "../components/States";

export function Callback() {
  const [params] = useSearchParams();
  const { completeSignIn, signIn } = useAuth();
  const navigate = useNavigate();
  const started = useRef(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; the code is single-use
    started.current = true;
    void completeSignIn(params.get("code") ?? "", params.get("state") ?? "").then((ok) => {
      if (ok) navigate("/", { replace: true });
      else setFailed(true);
    });
  }, [completeSignIn, navigate, params]);

  if (failed) {
    // the reason is announced by the header alert; offer the way forward here
    return (
      <section>
        <h1 className="font-serif text-2xl font-semibold">Sign-in did not complete</h1>
        <button
          type="button"
          onClick={() => void signIn()}
          className="mt-4 rounded bg-accent px-4 py-2 text-accent-ink"
        >
          Sign in again
        </button>
      </section>
    );
  }
  return <Skeleton lines={1} label="Signing in" />;
}
