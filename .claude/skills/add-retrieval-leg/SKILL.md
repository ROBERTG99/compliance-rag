---
name: add-retrieval-leg
description: 'Add a retrieval leg (search backend): interface, ACL filter test, hybrid wiring and ablation entry.'
---

# Add a retrieval leg

The graph has no model-invoked tools; legs are code-invoked.

1. Implement the leg behind the `VectorStore`/leg protocol in `src/compliance_rag/retrieval/` with a signature that takes `principal: Principal` and `as_of: date` — no unfiltered variant.
2. Build its filter from `retrieval/filters.py` so ACL, validity and `visible` are inside the backend query.
3. Add `tests/integration/test_<leg>.py::test_acl_filter_inside_query` (support principal never sees legal-only chunks, Hypothesis over random group assignments).
4. Wire it into `retrieval/hybrid.py` with its own timeout and `degraded` name.
5. Add an ablation configuration in `scripts/ablation.py` and rerun `make eval-ablation`.
6. Ask the `acl-auditor` subagent to trace the new path.
