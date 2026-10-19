import type { Persona } from "./config";

export interface Principal {
  sub: string;
  role: "analyst" | "legal" | "support" | "content_admin";
  groups: string[];
  name?: string;
  exp: number;
}

const TOKEN_KEY = "crag.token";
export const PKCE_KEY = "crag.pkce";

/** Reads the JWT payload for display and routing only; the API validates the signature. */
export function decodePrincipal(token: string, now: number = Date.now() / 1000): Principal | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as Partial<Principal>;
    if (
      !claims.sub ||
      !claims.role ||
      !Array.isArray(claims.groups) ||
      typeof claims.exp !== "number"
    ) {
      return null;
    }
    if (claims.exp <= now) return null;
    return claims as Principal;
  } catch {
    return null;
  }
}

export function personaOf(principal: Principal | null): Persona | "" {
  if (!principal) return "";
  return principal.role === "content_admin" ? "admin" : principal.role;
}

export const isAdmin = (principal: Principal | null): boolean =>
  principal?.role === "content_admin";

// sessionStorage can throw (private mode, blocked storage): the app still works, sign-in just does not persist
export function loadToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function takePkce(): { verifier: string; state: string } | null {
  try {
    const raw = sessionStorage.getItem(PKCE_KEY);
    sessionStorage.removeItem(PKCE_KEY);
    return raw ? (JSON.parse(raw) as { verifier: string; state: string }) : null;
  } catch {
    return null;
  }
}

export function storePkce(value: { verifier: string; state: string }): void {
  try {
    sessionStorage.setItem(PKCE_KEY, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}
