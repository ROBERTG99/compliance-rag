#!/usr/bin/env python3
"""PreToolUse guard for Bash, Write and Edit (BUILD.md §0 rule 8, §1.1, §7).

Blocks (exit 2, reason on stderr):
- attribution trailers in commit messages (Co-Authored-By, Claude-Session, "Generated with Claude Code");
- git identity changes (`git config user.*`, GIT_AUTHOR_* / GIT_COMMITTER_* assignments);
- force pushes, terraform apply/destroy, rm -rf of / or ~, repository creation or visibility changes;
- writes to existing files in evals/datasets/*.jsonl (new versioned files are allowed).

Fails open: malformed input or an internal error never blocks a tool call.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ATTRIBUTION = re.compile(r"co-authored-by|claude-session|generated with claude code", re.I)
DATASET = re.compile(r"(^|[\s'\"=/])(evals/datasets/[^\s'\"]+\.jsonl)")

FORBIDDEN_BASH: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bgit\s+(-c\s+\S+\s+)*config\b[^|;&]*\buser\.(name|email)\b"),
        "changing git identity config",
    ),
    (
        re.compile(r"(^|[\s;&|(])(export\s+)?GIT_(AUTHOR|COMMITTER)_(NAME|EMAIL|DATE)="),
        "setting GIT_AUTHOR_*/GIT_COMMITTER_*",
    ),
    (re.compile(r"\bgit\s+push\b[^|;&]*(\s--force\b|\s--force-with-lease\b|\s-f\b|\s\+\S)"), "force push"),
    (re.compile(r"\bterraform\s+(apply|destroy)\b"), "terraform apply/destroy"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+(/|~)(\s|/?$|/\*|\*)"), "rm -rf on / or ~"),
    (
        re.compile(r"\bgh\s+repo\s+(create|delete|edit\b[^|;&]*--visibility)"),
        "creating/deleting a repo or changing visibility",
    ),
]


def _block(reason: str) -> None:
    print(f"Blocked by .claude/hooks/pre_tool_guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def _project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def _is_existing_dataset(path_text: str) -> bool:
    path = Path(path_text)
    if not path.is_absolute():
        path = _project_dir() / path
    try:
        rel = path.resolve().relative_to(_project_dir().resolve())
    except ValueError:
        return False
    parts = rel.parts
    return (
        len(parts) >= 3
        and parts[0] == "evals"
        and parts[1] == "datasets"
        and rel.suffix == ".jsonl"
        and path.exists()
    )


def check_bash(command: str) -> None:
    if re.search(r"\bgit\b[^|;&]*\bcommit\b", command) and ATTRIBUTION.search(command):
        _block("commit attribution trailers are not allowed (BUILD.md §1.1)")
    for pattern, reason in FORBIDDEN_BASH:
        if pattern.search(command):
            _block(reason)
    writes = re.search(r"(>>?|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\btruncate\b|\brm\b)", command)
    if writes:
        for match in DATASET.finditer(command):
            target = match.group(2)
            # only block when the dataset file is the write target, not a read source before a pipe
            segment = command[writes.start() :]
            if target in segment and _is_existing_dataset(target):
                _block(f"{target} is an append-only versioned dataset; add a new .vN.jsonl file instead")


def check_file(tool_input: dict[str, object]) -> None:
    path = str(tool_input.get("file_path") or "")
    if path and _is_existing_dataset(path):
        _block(f"{path} is an append-only versioned dataset; add a new .vN.jsonl file instead")


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
    except Exception:
        sys.exit(0)
    try:
        if tool == "Bash":
            check_bash(str(tool_input.get("command", "")))
        elif tool in {"Write", "Edit", "MultiEdit"}:
            check_file(tool_input)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
