# Security policy

compliance-rag is a portfolio project: a local, offline-first system over a synthetic corpus for a
fictional company. It has no production deployment and holds no real data. Security issues in its code
are still taken seriously, because the patterns are meant to be reused.

## Supported versions

Only the latest commit on the default branch is supported.

## Reporting a vulnerability

Please report privately through GitHub's
[private vulnerability reporting](https://github.com/ROBERTG99/compliance-rag/security/advisories/new)
rather than a public issue. Include the affected file or endpoint, steps to reproduce (ideally a failing
test), and the impact you expect.

Issues of particular interest:

- any way for a persona to retrieve, cite, list or infer the existence of a document outside its groups;
- prompt-injection paths that get document instructions, canaries or unknown links into an answer;
- unverified text reaching a client;
- question, answer or document text in logs, traces or metrics;
- bypasses of the upload limits (size, pages, archive expansion).

## Scope

The development OIDC issuer (`apps/dev-oidc/`), its personas and the passwords in `compose.yaml` are
deliberately local development values and are out of scope. Findings in third-party images or packages
are welcome but are tracked through `make security` and Dependabot.

The threat model, the OWASP Top 10 for LLM applications mapping and the current scan results are in
[docs/security.md](docs/security.md).
