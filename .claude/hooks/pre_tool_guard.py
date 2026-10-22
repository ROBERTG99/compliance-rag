#!/usr/bin/env python3
"""PreToolUse guard for Bash, Write and Edit.

Blocks (exit 2, reason on stderr):
- attribution lines in commit messages or pull requests (Co-Authored-By, Claude-Session,
  "Generated with Claude Code"), including `git commit -F <file>`;
- git identity changes (`git config user.*` writes, `git -c user.*`, `--author`, GIT_AUTHOR_* /
  GIT_COMMITTER_* assignments);
- force pushes, terraform apply/destroy, recursive rm of / or ~, creating/forking/deleting a GitHub
  repository or changing its visibility;
- writes to existing files in evals/datasets/*.jsonl (new versioned files are allowed).

Commands are split into segments (`;`, `&&`, `||`, `|`, newlines) and tokenised with shlex, so a
pattern only matches inside one simple command. Fails open: malformed input or an internal error
never blocks a tool call.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

ATTRIBUTION = re.compile(r"co-authored-by|claude-session|generated with claude code", re.I)
IDENTITY_VAR = re.compile(r"^GIT_(AUTHOR|COMMITTER)_(NAME|EMAIL|DATE)=")
GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope"}
HOME_TARGETS = {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "${HOME}/"}


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
        len(parts) >= 3 and parts[0] == "evals" and parts[1] == "datasets" and rel.suffix == ".jsonl" and path.exists()
    )


def _tokens(segment: str) -> list[str]:
    lexer = shlex.shlex(segment, posix=True, punctuation_chars="<>&")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        return segment.split()


def _strip_env(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
        i += 1
    rest = tokens[i:]
    if rest[:1] in (["env"], ["sudo"], ["command"], ["exec"]):
        return _strip_env(rest[1:])
    return rest


def _check_identity_and_attribution(segment: str, tokens: list[str]) -> None:
    for tok in tokens:
        if IDENTITY_VAR.match(tok):
            _block("setting GIT_AUTHOR_*/GIT_COMMITTER_* is not allowed")
    cmd = _strip_env(tokens)
    if not cmd:
        return
    if cmd[0] == "export" and any(IDENTITY_VAR.match(t) for t in cmd[1:]):
        _block("setting GIT_AUTHOR_*/GIT_COMMITTER_* is not allowed")
    if cmd[0] == "git":
        args = cmd[1:]
        for i, tok in enumerate(args):
            if tok == "-c" and i + 1 < len(args) and args[i + 1].startswith("user."):
                _block("git -c user.* changes the git identity")
            if tok.startswith("-c") and tok[2:].startswith("user."):
                _block("git -c user.* changes the git identity")
        # skip values of -c / -C
        clean: list[str] = []
        skip = False
        for tok in args:
            if skip:
                skip = False
                continue
            if tok in {"-c", "-C"}:
                skip = True
                continue
            clean.append(tok)
        sub = clean[0] if clean else ""
        rest = clean[1:]
        if sub == "config":
            keys = [t for t in rest if t.startswith("user.")]
            if keys and not (GIT_CONFIG_READ & set(rest)) and (len(rest) - rest.index(keys[0]) > 1 or "--unset" in rest):
                _block("changing git config user.* is not allowed")
        if sub == "commit":
            if any(t == "--author" or t.startswith("--author=") for t in rest):
                _block("git commit --author changes the git identity")
            if ATTRIBUTION.search(segment):
                _block("commit attribution trailers are not allowed")
            for i, tok in enumerate(rest):
                path = None
                if tok in {"-F", "--file"} and i + 1 < len(rest):
                    path = rest[i + 1]
                elif tok.startswith("--file="):
                    path = tok.split("=", 1)[1]
                if path and path != "-":
                    try:
                        text = (Path(path) if Path(path).is_absolute() else _project_dir() / path).read_text()
                    except OSError:
                        text = ""
                    if ATTRIBUTION.search(text):
                        _block("commit message file contains attribution trailers")
        if sub == "push":
            for tok in rest:
                if tok in {"--force", "--force-with-lease", "--force-if-includes"} or tok.startswith("--force"):
                    _block("force push is not allowed")
                if re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", tok):
                    _block("force push is not allowed")
                if tok.startswith("+") and len(tok) > 1:
                    _block("force push (+refspec) is not allowed")
    if cmd[0] == "gh" and len(cmd) >= 3:
        if cmd[1] == "repo" and cmd[2] in {"create", "delete", "fork", "rename", "archive"}:
            _block("creating, forking, renaming or deleting a GitHub repository is not allowed")
        if cmd[1] == "repo" and cmd[2] == "edit" and any(t.startswith("--visibility") for t in cmd):
            _block("changing repository visibility is not allowed")
        if cmd[1] == "pr" and cmd[2] in {"create", "edit", "comment", "review"} and ATTRIBUTION.search(segment):
            _block("pull request attribution lines are not allowed")


def _check_destructive(tokens: list[str]) -> None:
    cmd = _strip_env(tokens)
    if not cmd:
        return
    if cmd[0] == "terraform" and any(t in {"apply", "destroy"} for t in cmd[1:]):
        _block("terraform apply/destroy is not allowed")
    if cmd[0] == "rm":
        flags = [t for t in cmd[1:] if t.startswith("-")]
        recursive = any(t in {"--recursive", "-r", "-R"} or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", t) for t in flags)
        targets = [t for t in cmd[1:] if not t.startswith("-")]
        home = os.path.expanduser("~")
        if recursive and any(t in HOME_TARGETS or t.rstrip("/") in {home, ""} for t in targets):
            _block("recursive rm of / or ~ is not allowed")


def _write_targets(tokens: list[str]) -> list[str]:
    targets: list[str] = []
    for i, tok in enumerate(tokens):
        if tok in {">", ">>", ">|", "&>", "&>>"} and i + 1 < len(tokens):
            targets.append(tokens[i + 1])
    cmd = _strip_env([t for t in tokens if t not in {">", ">>", ">|", "&>", "&>>", ">&", "<", "<<"}])
    if not cmd:
        return targets
    args = [t for t in cmd[1:] if not t.startswith("-")]
    name = cmd[0]
    if name == "tee":
        targets += args
    elif name in {"rm", "truncate", "shred", "unlink"}:
        targets += args
    elif name in {"cp", "install", "ln", "rsync"} and args:
        targets.append(args[-1])
    elif name == "mv":
        targets += args  # moving away also removes the source
    elif name == "sed" and any(t == "-i" or t.startswith("-i") or t.startswith("--in-place") for t in cmd[1:]):
        targets += args[1:]
    return targets


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def split_segments(command: str) -> list[str]:
    """Split on unquoted `;`, `&&`, `||`, `|` and newlines; heredoc bodies are dropped (data, not commands)."""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    pending_heredocs: list[str] = []
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(command[i : i + 2])
            i += 2
            continue
        two = command[i : i + 2]
        if two in {"&&", "||"} or ch in {";", "\n"} or (ch == "|" and two != "|&"):
            segment = "".join(buf)
            segments.append(segment)
            pending_heredocs += [m.group(2) for m in HEREDOC.finditer(segment)]
            buf = []
            i += 2 if two in {"&&", "||"} else 1
            if ch == "\n" and pending_heredocs:
                # skip heredoc bodies line by line until each delimiter
                while pending_heredocs and i < n:
                    end = command.find("\n", i)
                    line = command[i:] if end == -1 else command[i:end]
                    i = n if end == -1 else end + 1
                    if line.strip() == pending_heredocs[0]:
                        pending_heredocs.pop(0)
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments


def check_bash(command: str) -> None:
    for segment in split_segments(command):
        if not segment.strip():
            continue
        tokens = _tokens(segment)
        _check_identity_and_attribution(segment, tokens)
        _check_destructive(tokens)
        for target in _write_targets(tokens):
            if _is_existing_dataset(target):
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
