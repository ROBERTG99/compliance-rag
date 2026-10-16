---
name: add-eval-case
description: 'Add evaluation cases as a new versioned dataset file without editing existing ones.'
---

# Add eval cases

1. Never edit `evals/datasets/*.vN.jsonl` (the pre-tool hook blocks it). Create `questions.v(N+1).jsonl` that contains all previous rows plus the new ones, or a separate named file referenced by a suite.
2. Row schema: `{"id", "split": "dev"|"test", "input": {"question", "as_of", "persona"}, "expected": {...}, "tags": [...], "meta": {"gold": [...]}}`.
3. New cases from feedback triage go to `dev` only.
4. Point the suite (`evals/suites/*.yaml`) at the new file and record the change in `docs/DECISIONS.md`.
