# 0008. Vite single-page app over Next.js

## Status

Accepted

## Date

2026-10-17

## Context

The web client is an authenticated tool: ask a question, follow a streamed answer, open the cited
evidence, browse the library, send feedback, and (for admins) view jobs and the evaluation report. All
data comes from the FastAPI service, which is the only place where ACL and validity are decided. The
client has to follow a Server-Sent Events stream that needs a bearer token and resume with
`Last-Event-ID`, and the stack has to run offline with no font or script CDNs.

## Decision

The UI is a React 19 single-page app built with Vite and served as static files
(`web/package.json`, `web/vite.config.ts`). Routing uses React Router and server state uses TanStack
Query. The production image builds the bundle in a Node stage and serves it from non-root nginx, with
`try_files $uri /index.html` for client-side routes (`docker/web.Dockerfile`, `docker/nginx.conf:49-51`).
nginx proxies `/v1`, `/healthz` and `/readyz` to the API (unbuffered, for SSE) and `/oidc/` to the dev
issuer so the token exchange is same-origin (`docker/nginx.conf:29-47`). Sign-in is authorization code
with PKCE, and the token is kept in `sessionStorage` (`web/src/auth/session.ts`,
`docs/DECISIONS.md` 2026-10-17 row on SPA sign-in). The stream is read with `fetch`, a bearer header and
`Last-Event-ID` (`web/src/api/sse.ts:65-69`). The API contract is generated from `docs/openapi.json`
(`web/package.json`, script `gen:api`).

## Alternatives considered

- **Next.js with server components or API routes.** Rejected: it adds a Node server runtime to run and
  patch, and a second place where requests, tokens and cached data can be handled. Server-rendered or
  cached pages built with a user's identity are a leak risk in a system whose central rule is that
  restricted text must not reach the wrong user. The pages are behind login, so server rendering for
  search engines has no value here.
- **Next.js as a static export.** Rejected: it would give a static bundle like Vite but with a heavier
  framework for no feature used here.
- **Server-rendered templates from FastAPI.** Rejected: streaming claims, citation chips and the evidence
  viewer are interactive, and the typed OpenAPI client keeps UI and API in step.

## Consequences

Positive:

- Production is only static files plus an nginx proxy: no Node process, and the image runs as a
  non-root user with the unused nginx modules removed (`docker/web.Dockerfile`, `docs/DECISIONS.md`
  2026-10-17 row on image hygiene).
- All authorisation stays in the API. The SPA decodes the token only for display and routing; admin
  screens render the not-found page for other roles, while the API still answers 403 or 404 itself.
- One Node toolchain covers unit tests (Vitest), type checks, Playwright end-to-end tests and axe
  accessibility checks at 1280 and 375 px (`docs/DECISIONS.md`, 2026-10-17 rows on Playwright and
  accessibility).

Negative:

- A client-side cache can outlive an identity. Review reproduced a restricted-row leak after an
  in-page persona switch; the app now cancels and clears the whole query cache on every token change and
  remounts the ask run provider, which aborts any open stream (`web/src/auth/AuthProvider.tsx:21-22`, `docs/DECISIONS.md` 2026-10-17 row on cache
  clearing).
- A token in `sessionStorage` is readable by script on the page, unlike an httpOnly cookie held by a
  server-side backend-for-frontend. The repo limits exposure with a strict content security policy
  (`docker/nginx.conf:25`), session-scoped storage and self-hosted fonts, but does not remove the risk.
- No server rendering: first paint waits for the bundle. Acceptable for a logged-in internal tool; not
  measured here.
- The dev persona switcher mints tokens for any persona, so it is compiled in only for `vite dev`, tests
  and builds with `VITE_DEV_PERSONAS=1` (`docker/web.Dockerfile`, `docs/DECISIONS.md` 2026-10-17 row).
