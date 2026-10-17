import { useCallback } from "react";
import { useAuth } from "../auth/context";
import { ApiError, apiFetch, type RequestOptions } from "./client";

/** `apiFetch` bound to the signed-in user's token; a 401 (expired or revoked) signs the user out. */
export function useApi(): <T>(path: string, opts?: RequestOptions) => Promise<T> {
  const { token, signOut } = useAuth();
  return useCallback(
    async <T>(path: string, opts?: RequestOptions): Promise<T> => {
      try {
        return await apiFetch<T>(path, token, opts);
      } catch (exc) {
        if (exc instanceof ApiError && exc.status === 401 && token) signOut();
        throw exc;
      }
    },
    [token, signOut],
  );
}
