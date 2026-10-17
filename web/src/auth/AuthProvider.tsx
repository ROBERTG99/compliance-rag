import { useCallback, useMemo, useState, type ReactNode } from "react";
import { AuthContext, type Auth } from "./context";
import type { Persona } from "./config";
import { authorizeUrl, createPkcePair, devToken, exchangeCode, randomToken } from "./pkce";
import { decodePrincipal, loadToken, saveToken, storePkce, takePkce } from "./session";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => {
    const stored = loadToken();
    return stored && decodePrincipal(stored) ? stored : null;
  });
  const [error, setError] = useState<string | null>(null);

  const setToken = useCallback((next: string | null) => {
    if (next && !decodePrincipal(next))
      throw new Error("the identity provider returned an unusable token");
    saveToken(next);
    setTokenState(next);
  }, []);

  const signIn = useCallback(async () => {
    const { verifier, challenge } = await createPkcePair();
    const state = randomToken(16);
    storePkce({ verifier, state });
    window.location.assign(authorizeUrl(challenge, state));
  }, []);

  const completeSignIn = useCallback(
    async (code: string, state: string) => {
      const pending = takePkce();
      if (!pending || pending.state !== state) {
        setError(
          "Sign-in failed: the response did not match this browser's request. Please sign in again.",
        );
        return false;
      }
      try {
        setToken(await exchangeCode(code, pending.verifier));
        setError(null);
        return true;
      } catch (exc) {
        setError(`Sign-in failed: ${(exc as Error).message}`);
        return false;
      }
    },
    [setToken],
  );

  const switchPersona = useCallback(
    async (persona: Persona) => {
      try {
        setToken(await devToken(persona));
        setError(null);
      } catch (exc) {
        setError(`Persona switch failed: ${(exc as Error).message}`);
      }
    },
    [setToken],
  );

  const signOut = useCallback(() => setToken(null), [setToken]);

  const value = useMemo<Auth>(
    () => ({
      token,
      principal: token ? decodePrincipal(token) : null,
      error,
      signIn,
      completeSignIn,
      switchPersona,
      signOut,
    }),
    [token, error, signIn, completeSignIn, switchPersona, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
