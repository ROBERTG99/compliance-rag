import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "../App";
import { createQueryClient } from "../api/queryClient";
import { AuthProvider } from "../auth/AuthProvider";

const PRINCIPALS: Record<string, { sub: string; role: string; groups: string[] }> = {
  analyst: { sub: "analyst@northwind.test", role: "analyst", groups: ["all", "compliance"] },
  legal: { sub: "legal@northwind.test", role: "legal", groups: ["all", "compliance", "legal"] },
  support: { sub: "support@northwind.test", role: "support", groups: ["all", "support"] },
  admin: { sub: "admin@northwind.test", role: "content_admin", groups: ["all", "compliance"] },
};

const b64url = (value: unknown) =>
  btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

/** An unsigned JWT-shaped token (the SPA only decodes claims; the API verifies signatures). */
export function fakeToken(persona: string, ttlS = 3600): string {
  const claims = { ...PRINCIPALS[persona], exp: Math.floor(Date.now() / 1000) + ttlS };
  return `${b64url({ alg: "RS256" })}.${b64url(claims)}.sig`;
}

export interface FakeResponse {
  status: number;
  body: unknown;
  headers?: Record<string, string>;
}

export interface Call {
  url: string;
  init?: RequestInit;
}

/** Stub global fetch; the handler sees each call in order. */
export function mockFetch(
  handler: (url: string, init?: RequestInit) => FakeResponse | Response,
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      calls.push({ url, init });
      const res = handler(url, init);
      if (res instanceof Response) return res;
      const contentType = res.status >= 400 ? "application/problem+json" : "application/json";
      return new Response(JSON.stringify(res.body), {
        status: res.status,
        headers: { "Content-Type": contentType, ...res.headers },
      });
    }),
  );
  return calls;
}

export function signInAs(persona: string): void {
  sessionStorage.setItem("crag.token", fakeToken(persona));
}

export function renderApp(path = "/") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}
