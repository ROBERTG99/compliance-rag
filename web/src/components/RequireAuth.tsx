import type { ReactNode } from "react";
import { useAuth } from "../auth/context";
import { isAdmin } from "../auth/session";
import { NotFound } from "../routes/NotFound";

export function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { principal, signIn } = useAuth();
  if (!principal) {
    return (
      <section className="max-w-prose">
        <h1 className="font-serif text-2xl font-semibold">Sign in to continue</h1>
        <p className="mt-2 text-muted">Answers depend on the policies your groups may read.</p>
        <button
          type="button"
          onClick={() => void signIn()}
          className="mt-4 rounded bg-accent px-4 py-2 text-accent-ink"
        >
          Sign in
        </button>
      </section>
    );
  }
  // admin screens look like any unknown page to other roles
  if (admin && !isAdmin(principal)) return <NotFound />;
  return <>{children}</>;
}
