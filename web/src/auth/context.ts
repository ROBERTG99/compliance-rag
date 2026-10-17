import { createContext, useContext } from "react";
import type { Persona } from "./config";
import type { Principal } from "./session";

export interface Auth {
  token: string | null;
  principal: Principal | null;
  error: string | null;
  signIn: () => Promise<void>;
  completeSignIn: (code: string, state: string) => Promise<boolean>;
  switchPersona: (persona: Persona) => Promise<void>;
  signOut: () => void;
}

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside <AuthProvider>");
  return auth;
}
