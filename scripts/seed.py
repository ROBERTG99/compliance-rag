"""Seed the synthetic corpus from the host (``make seed`` runs the same command in the ``seed`` container).

    uv run python scripts/seed.py [--force] [--qdrant]

Idempotent: a second run with the same corpus fingerprint reports ``already_seeded`` and writes nothing.
"""

from __future__ import annotations

import sys

from compliance_rag.cli import app

if __name__ == "__main__":
    sys.argv = ["crag", "seed", *sys.argv[1:]]
    app()
