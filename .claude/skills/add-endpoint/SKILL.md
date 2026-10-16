---
name: add-endpoint
description: 'Add a FastAPI endpoint with auth, problem+json errors, OpenAPI, typed web client and tests.'
---

# Add an endpoint

1. Write an integration test in `tests/integration/test_<area>_api.py` (auth role, happy path, 404-for-unauthorized, 422).
2. Add the route in `src/compliance_rag/api/routes/<area>.py` with Pydantic request/response models and `Depends(require_role(...))`.
3. Errors via `api/errors.py` (RFC 9457). Audit actions via `db/audit.py` where the action is in the audit enum.
4. Regenerate the spec and types: `make docs` (`docs/openapi.json`, `web/src/api/schema.d.ts`).
5. Schemathesis contract test runs automatically from `docs/openapi.json`.
