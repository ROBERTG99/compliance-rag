---
name: add-corpus-domain
description: 'Add a new policy domain to the synthetic corpus generator and its questions.'
---

# Add a corpus domain

1. Add the domain to `data/generator/catalog.py` (prefix of 2–4 capital letters, topics, fact templates with units).
2. Keep facts unique per policy (distinct entity names) so questions have one gold span.
3. Extend question templates in `data/generator/questions.py`; new questions go to a new dataset version.
4. Run `make corpus` twice and check the manifest hash is identical (`tests/unit/data/test_generator.py`).
5. `make seed` and `make eval` on dev to check retrieval quality.
