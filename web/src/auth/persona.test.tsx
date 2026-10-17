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

  await user.selectOptions(screen.getByLabelText(/persona/i), "legal");
  const nav = await screen.findByRole("navigation", { name: /main/i });
  await waitFor(() => expect(screen.getByText(/legal@northwind\.test/)).toBeInTheDocument());
  expect(within(nav).queryByRole("link", { name: /ingestion jobs/i })).toBeNull();
  expect(within(nav).queryByRole("link", { name: /feedback review/i })).toBeNull();

  await user.selectOptions(screen.getByLabelText(/persona/i), "admin");
  await waitFor(() =>
    expect(within(nav).getByRole("link", { name: /ingestion jobs/i })).toBeInTheDocument(),
  );
  expect(within(nav).getByRole("link", { name: /feedback review/i })).toBeInTheDocument();
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
