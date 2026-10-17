import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/context";
import { oidc, PERSONAS, type Persona } from "../auth/config";
import { isAdmin, personaOf } from "../auth/session";
import { ThemeToggle } from "./ThemeToggle";

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded px-2 py-1 ${isActive ? "bg-accent text-accent-ink" : "hover:underline"}`;

export function Shell() {
  const { principal, error, signIn, signOut, switchPersona } = useAuth();
  const admin = isAdmin(principal);
  return (
    <div className="min-h-screen bg-paper text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2">
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
                  className="rounded border border-rule bg-surface px-1 py-0.5"
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
                <button type="button" onClick={signOut} className="underline">
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
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
