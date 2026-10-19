#!/usr/bin/env python3
"""PostToolUse formatter for Write|Edit: ruff format for Python, prettier for web files.

No-op when the formatter is missing or the file type is unknown; never fails the tool call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PRETTIER_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".html"}


def _project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def _ruff() -> str | None:
    local = _project_dir() / ".venv" / "bin" / "ruff"
    return str(local) if local.exists() else shutil.which("ruff")


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        path = Path(str((payload.get("tool_input") or {}).get("file_path") or ""))
    except Exception:
        return
    if not path.is_file():
        return
    try:
        if path.suffix == ".py":
            ruff = _ruff()
            if ruff:
                subprocess.run([ruff, "format", "--quiet", str(path)], timeout=30, check=False)
        elif path.suffix in PRETTIER_SUFFIXES:
            prettier = _project_dir() / "web" / "node_modules" / ".bin" / "prettier"
            web = (_project_dir() / "web").resolve()
            if prettier.exists() and web in path.resolve().parents:
                subprocess.run(
                    [str(prettier), "--write", "--log-level", "silent", str(path)],
                    cwd=web,
                    timeout=30,
                    check=False,
                )
    except Exception:
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
