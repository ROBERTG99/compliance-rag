---
name: new-adr
description: 'Create a new Architecture Decision Record in docs/adr with the standard template.'
---

# New ADR

1. Pick the next number: `ls docs/adr | sort | tail -1`.
2. Create `docs/adr/NNNN-<kebab-title>.md` with sections: Status (Accepted), Date, Context, Decision, Alternatives considered (with why rejected), Consequences.
3. Add a row to `docs/DECISIONS.md` linking the ADR.
4. Run markdownlint on the file.
