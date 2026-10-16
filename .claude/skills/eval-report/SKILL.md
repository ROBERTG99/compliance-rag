---
name: eval-report
description: 'Regenerate evals/REPORT.md from the latest offline run and check the thresholds in BUILD.md §11.'
---

# Eval report

1. Ensure the stack is up and seeded (`make up`).
2. Run `make eval` (`scripts/run_evals.py`): evalgate runs `evals/suites/rag.yaml` and `evals/suites/retrieval.yaml` on the test split, checks against `evals/reports/baseline.json`, and writes `evals/REPORT.md`.
3. Optionally `make eval-ablation` to refresh the ablation table.
4. Verify each §11 threshold in the generated report; never edit numbers by hand.
5. Offline numbers are labelled FakeLLM-produced; live numbers only from `make eval-live`.
