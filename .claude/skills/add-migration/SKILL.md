---
name: add-migration
description: 'Add an Alembic migration with upgrade and downgrade, tested against Postgres.'
---

# Add a migration

1. Create `migrations/versions/NNNN_<name>.py` with `revision`, `down_revision` set to the current head.
2. Write raw SQL via `op.execute` for both `upgrade()` and `downgrade()`; keep constraints in SQL (CHECKs, partial unique indexes).
3. Add an integration test in `tests/integration/test_migrations.py` that upgrades, asserts the new structure/constraint, and downgrades.
4. `make migrate` locally against the compose Postgres; `uv run pytest tests/integration/test_migrations.py -q`.
