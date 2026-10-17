import { useCallback } from "react";
import { useAuth } from "../auth/context";
import { apiFetch, type RequestOptions } from "./client";

/** `apiFetch` bound to the signed-in user's token. */
export function useApi(): <T>(path: string, opts?: RequestOptions) => Promise<T> {
  const { token } = useAuth();
  return useCallback(
    <T>(path: string, opts?: RequestOptions) => apiFetch<T>(path, token, opts),
    [token],
  );
}
