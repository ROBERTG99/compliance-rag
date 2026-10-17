import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/context";
import { oidc, PERSONAS, type Persona } from "../auth/config";
import { isAdmin, personaOf } from "../auth/session";
import { AskRunProvider } from "../routes/ask/AskRunProvider";
import { ThemeToggle } from "./ThemeToggle";

const link = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-8 items-center rounded px-2 py-1 ${isActive ? "bg-accent text-accent-ink" : "hover:underline"}`;

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Ask"],
  [/^\/evidence\//, "Evidence"],
  [/^\/library\/.+/, "Document"],
  [/^\/library$/, "Document library"],
  [/^\/evaluation$/, "Evaluation"],
  [/^\/jobs$/, "Ingestion jobs"],
  [/^\/feedback$/, "Feedback review"],
  [/^\/callback$/, "Signing in"],
];

/** WCAG 2.4.2 / 2.4.3: a distinct title per screen, and focus moves to the content after navigation. */
function usePageChange(main: React.RefObject<HTMLElement | null>) {
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => {
    const name = TITLES.find(([re]) => re.test(pathname))?.[1] ?? "Not found";
    document.title = `${name} · Northwind Compliance Assistant`;
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus();
  }, [pathname, main]);
}

export function Shell() {
  const { principal, error, signIn, signOut, switchPersona } = useAuth();
  const main = useRef<HTMLElement>(null);
  usePageChange(main);
  const admin = isAdmin(principal);
  const identity = principal ? `${principal.sub}|${principal.role}` : "anonymous";
  return (
    <div className="min-h-screen bg-paper text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:border focus:border-control focus:bg-surface focus:p-2 focus:text-ink"
      >
        Skip to content
      </a>
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <p className="font-serif text-lg font-semibold">Northwind Compliance Assistant</p>
          <nav aria-label="Main" className="flex flex-wrap gap-1 text-sm">
            <NavLink to="/" end className={link}>
              Ask
            </NavLink>
            <NavLink to="/library" className={link}>
              Library
            </NavLink>
            <NavLink to="/evaluation" className={link}>
              Evaluation
            </NavLink>
            {admin ? (
              <>
                <NavLink to="/jobs" className={link}>
                  Ingestion jobs
                </NavLink>
                <NavLink to="/feedback" className={link}>
                  Feedback review
                </NavLink>
              </>
            ) : null}
          </nav>
          <div className="ml-auto flex flex-wrap items-center gap-3 text-sm">
            {oidc.devPersonas ? (
              <label className="flex items-center gap-1">
                <span>Persona (dev)</span>
                <select
                  className="min-h-8 rounded border border-control bg-surface px-1 py-1"
                  value={personaOf(principal)}
                  onChange={(e) => void switchPersona(e.target.value as Persona)}
                >
                  <option value="" disabled>
                    choose…
                  </option>
                  {PERSONAS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {principal ? (
              <>
                <span>
                  {principal.sub} <span className="text-muted">({principal.role})</span>
                </span>
                <button type="button" onClick={signOut} className="min-h-8 underline">
                  Sign out
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => void signIn()}
                className="rounded bg-accent px-3 py-1 text-accent-ink"
              >
                Sign in
              </button>
            )}
            <ThemeToggle />
          </div>
        </div>
        {error ? (
          <p role="alert" className="mx-auto max-w-6xl px-4 pb-2 text-sm text-restricted">
            {error}
          </p>
        ) : null}
      </header>
      <main
        id="main"
        ref={main}
        tabIndex={-1}
        className="mx-auto max-w-6xl px-4 py-6 focus:outline-none"
      >
        {/* a new identity gets fresh screens and a fresh ask run (any open stream is aborted); the header
            stays mounted so focus on the persona switcher survives the switch */}
        <AskRunProvider key={identity}>
          <Outlet key={identity} />
        </AskRunProvider>
      </main>
    </div>
  );
}
