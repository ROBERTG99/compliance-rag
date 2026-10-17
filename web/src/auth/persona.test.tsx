import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createPkcePair, s256 } from "./pkce";
import { decodePrincipal } from "./session";
import { renderApp, fakeToken, mockFetch } from "../test/render";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test("PKCE challenge is the S256 of the verifier", async () => {
  const { verifier, challenge } = await createPkcePair();
  expect(verifier).toMatch(/^[A-Za-z0-9_-]{43,128}$/);
  expect(challenge).toBe(await s256(verifier));
  expect(challenge).not.toContain("=");
});

test("decodePrincipal reads sub, role and groups and rejects expired tokens", () => {
  const principal = decodePrincipal(fakeToken("legal"));
  expect(principal).toMatchObject({ sub: "legal@northwind.test", role: "legal" });
  expect(principal?.groups).toContain("legal");
  expect(decodePrincipal(fakeToken("legal", -10))).toBeNull();
  expect(decodePrincipal("not-a-jwt")).toBeNull();
});

test("switching persona signs in and hides admin navigation from other roles", async () => {
  const calls = mockFetch((url, init) => {
    if (url.endsWith("/oidc/dev/token")) {
      const persona = JSON.parse(String(init?.body)).persona as string;
      return { status: 200, body: { access_token: fakeToken(persona) } };
    }
    return { status: 404, body: {} };
  });
  renderApp("/");
  const user = userEvent.setup();

  // the shell is rebuilt for each identity, so look the navigation up again after every switch
  const nav = () => screen.getByRole("navigation", { name: /main/i });
  await user.selectOptions(screen.getByLabelText(/persona/i), "legal");
  await waitFor(() => expect(screen.getByText(/legal@northwind\.test/)).toBeInTheDocument());
  expect(within(nav()).queryByRole("link", { name: /ingestion jobs/i })).toBeNull();
  expect(within(nav()).queryByRole("link", { name: /feedback review/i })).toBeNull();

  await user.selectOptions(screen.getByLabelText(/persona/i), "admin");
  await waitFor(() =>
    expect(within(nav()).getByRole("link", { name: /ingestion jobs/i })).toBeInTheDocument(),
  );
  expect(within(nav()).getByRole("link", { name: /feedback review/i })).toBeInTheDocument();
  expect(calls.map((c) => c.url)).toEqual(["/oidc/dev/token", "/oidc/dev/token"]);
});

test("the OIDC callback exchanges the code with the stored verifier and checks state", async () => {
  sessionStorage.setItem("crag.pkce", JSON.stringify({ verifier: "v".repeat(43), state: "s1" }));
  const calls = mockFetch(() => ({ status: 200, body: { access_token: fakeToken("analyst") } }));
  renderApp("/callback?code=abc&state=s1");
  await waitFor(() => expect(screen.getByText(/analyst@northwind\.test/)).toBeInTheDocument());
  const form = new URLSearchParams(String(calls[0].init?.body));
  expect(calls[0].url).toBe("/oidc/token");
  expect(form.get("code")).toBe("abc");
  expect(form.get("code_verifier")).toBe("v".repeat(43));
  expect(form.get("grant_type")).toBe("authorization_code");
  expect(sessionStorage.getItem("crag.pkce")).toBeNull();
});

test("a callback with the wrong state is refused without calling the token endpoint", async () => {
  sessionStorage.setItem("crag.pkce", JSON.stringify({ verifier: "v".repeat(43), state: "s1" }));
  const calls = mockFetch(() => ({ status: 200, body: {} }));
  renderApp("/callback?code=abc&state=forged");
  expect(await screen.findByRole("alert")).toHaveTextContent(/sign-in failed/i);
  expect(calls).toHaveLength(0);
});

test("switching persona drops everything fetched or answered under the previous identity", async () => {
  sessionStorage.setItem("crag.token", fakeToken("legal"));
  const libraryCalls: string[] = [];
  mockFetch((url, init) => {
    if (url.endsWith("/oidc/dev/token")) {
      return {
        status: 200,
        body: { access_token: fakeToken(JSON.parse(String(init?.body)).persona) },
      };
    }
    if (url.startsWith("/v1/documents")) {
      const auth = new Headers(init?.headers).get("Authorization") ?? "";
      libraryCalls.push(auth);
      const claims = JSON.parse(
        atob((auth.split(" ")[1] ?? "..").split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
      );
      const legal = claims.role === "legal";
      const items = legal
        ? [
            {
              document_id: "CMP-0215",
              title: "Litigation Hold",
              domain: "complaints",
              owner: "Legal",
              current_version: 2,
              versions: 2,
              restricted: true,
            },
          ]
        : [];
      return { status: 200, body: { items, next_cursor: null } };
    }
    return { status: 404, body: {} };
  });
  renderApp("/library");
  expect(await screen.findByText("CMP-0215")).toBeInTheDocument();
  await userEvent.setup().selectOptions(screen.getByLabelText(/persona/i), "support");
  await waitFor(() => expect(screen.getByText(/support@northwind\.test/)).toBeInTheDocument());
  await waitFor(() => expect(screen.queryByText("CMP-0215")).toBeNull());
  expect(libraryCalls.length).toBeGreaterThanOrEqual(2); // refetched as the new identity, not served from cache
});
