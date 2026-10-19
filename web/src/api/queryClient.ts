import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./client";

/** The single TanStack Query client: retry only what the API marks as retryable, never 4xx. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) =>
          error instanceof ApiError && error.retryable && error.status !== 429 && count < 2,
      },
      mutations: { retry: false },
    },
  });
}
