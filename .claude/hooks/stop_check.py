#!/usr/bin/env python3
"""Stop hook: run `make check-fast` (< 60 s) and ask Claude to keep working once if it fails.

Honours `stop_hook_active` so it never loops; a timeout or a missing tool never blocks.
`CRAG_STOP_CHECK_CMD` overrides the command (used by tests).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    command = os.environ.get("CRAG_STOP_CHECK_CMD", "make check-fast")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": f"`{command}` failed; fix it before stopping.\n{tail}",
                }
            )
        )


if __name__ == "__main__":
    main()
    sys.exit(0)
