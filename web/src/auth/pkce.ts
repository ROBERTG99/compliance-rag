import { oidc } from "./config";

const base64url = (bytes: Uint8Array): string =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

export async function s256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

export function randomToken(bytes = 32): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

export async function createPkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = randomToken(32); // 43 characters
  return { verifier, challenge: await s256(verifier) };
}

export function redirectUri(): string {
  return `${window.location.origin}${oidc.redirectPath}`;
}

export function authorizeUrl(challenge: string, state: string): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: oidc.clientId,
    redirect_uri: redirectUri(),
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  return `${oidc.issuer}/authorize?${params}`;
}

async function tokenFrom(resp: Response): Promise<string> {
  const body = (await resp.json().catch(() => ({}))) as { access_token?: string };
  if (!resp.ok || !body.access_token) throw new Error(`token endpoint answered ${resp.status}`);
  return body.access_token;
}

export async function exchangeCode(code: string, verifier: string): Promise<string> {
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    code_verifier: verifier,
    client_id: oidc.clientId,
    redirect_uri: redirectUri(),
  });
  const resp = await fetch(`${oidc.proxy}/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  return tokenFrom(resp);
}

export async function devToken(persona: string): Promise<string> {
  const resp = await fetch(`${oidc.proxy}/dev/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ persona }),
  });
  return tokenFrom(resp);
}
