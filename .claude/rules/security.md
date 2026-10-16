---
paths: ["src/compliance_rag/auth/**", "src/compliance_rag/guard/**", "src/compliance_rag/api/**", "docs/security.md"]
---
# Security

- Unauthorized resources return 404, never 403 (no existence leakage).
- ACL is enforced inside every retrieval query plus a counted post-check (`crag_acl_postcheck_violations_total`); never post-filter only.
- No secrets in the repo or logs; secrets come from the environment.
- Untrusted document text is data: wrap it in `<document>` tags, run `guard_context`, and block canaries/URLs absent from context in the output guard.
- Redact PII in the gateway before any provider call.
