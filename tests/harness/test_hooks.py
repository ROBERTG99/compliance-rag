"""Claude Code hooks behave as documented in BUILD.md §7 (T-05)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = Path(os.environ.get("CRAG_HOOKS_DIR", ROOT / ".claude" / "hooks"))
TRAILER = "Co-Authored-By"


def _run(
    hook: str, payload: dict[str, object], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **(env or {})}
    return subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
        check=False,
    )


def _bash(command: str, project: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {"CLAUDE_PROJECT_DIR": str(project)} if project else None
    return _run("pre_tool_guard.py", {"tool_name": "Bash", "tool_input": {"command": command}}, env=env)


def test_pretool_blocks_coauthor_trailer() -> None:
    result = _bash(f'git commit -m "feat: x\n\n{TRAILER}: Someone <a@b.c>"')
    assert result.returncode == 2
    assert "attribution" in result.stderr.lower()


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "feat: x" -m "Claude-Session: https://claude.ai/code/x"',
        'git commit -m "docs: y\n\nGenerated with Claude Code"',
        "git config user.email someone@example.com",
        "git config --global user.name Bot",
        "export GIT_AUTHOR_NAME=Bot",
        "GIT_COMMITTER_EMAIL=x@y.z git commit -m 'chore: z'",
        "git push --force origin main",
        "git push -f",
        "terraform apply -auto-approve",
        "terraform destroy",
        "rm -rf /",
        "rm -rf ~/",
        "gh repo create foo --public",
        "gh repo edit --visibility public",
        "gh repo fork ROBERTG99/x",
        'git commit --author="Bot <b@x>" -m "feat: x"',
        "git -c user.name=Bot -c user.email=b@x commit -m 'feat: x'",
        "git push -fu origin main",
        "git push -uf origin main",
        "git push origin +main",
        "git push --force-with-lease",
        "rm -r -f /",
        "rm -Rf /",
        'rm -rf "$HOME"',
        "rm --recursive --force /",
        "terraform -chdir=infra apply",
        'gh pr create --title t --body "Generated with Claude Code"',
        "git config --unset user.email",
    ],
)
def test_pretool_blocks_forbidden_bash(command: str) -> None:
    assert _bash(command).returncode == 2, command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'feat(api): add ask route'",
        "git log --format=%B | grep -E 'Co-Authored-By|Claude-Session|Generated with Claude Code'",
        'echo "$GIT_AUTHOR_NAME"',
        "git push -u origin feat/x",
        "make check-fast",
        "cat evals/datasets/questions.v1.jsonl | head",
        "uv run crag corpus generate",
        "git config --get user.email",
        "git var GIT_AUTHOR_IDENT",
        "git commit -m 'feat: x' && git log --format=%B | grep Co-Authored-By",
        "docker compose run --rm api crag seed",
        "rm -rf ./build /tmp/x",
        "make x 2>&1 | tail -3",
        "cat > notes.md <<'EOF'\ngit push -f\nrm -rf /\nEOF\necho done",
    ],
)
def test_pretool_allows_normal_bash(command: str) -> None:
    result = _bash(command)
    assert result.returncode == 0, (command, result.stderr)


def test_pretool_blocks_edit_of_existing_dataset(tmp_path: Path) -> None:
    datasets = tmp_path / "evals" / "datasets"
    datasets.mkdir(parents=True)
    existing = datasets / "q.v1.jsonl"
    existing.write_text("{}\n")
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    for tool in ("Edit", "Write"):
        payload = {"tool_name": tool, "tool_input": {"file_path": str(existing)}}
        assert _run("pre_tool_guard.py", payload, env=env).returncode == 2, tool
    rel = "evals/datasets/q.v1.jsonl"
    for command in (
        f"echo '{{}}' > {rel}",
        f"sed -i 's/a/b/' {rel}",
        f"cat x >> {rel}",
        f"cp other.jsonl {rel}",
        f"mv {rel} /tmp/q.jsonl",
        f"rm {rel}",
        f"echo x | tee -a {rel}",
    ):
        assert _bash(command, tmp_path).returncode == 2, command
    for command in (
        f"cat {rel} | head",
        f"cp {rel} evals/datasets/q.v2.jsonl",
        f"docker compose run --rm api wc -l {rel}",
        f"make x 2>&1 | tail; wc -l {rel}",
    ):
        result = _bash(command, tmp_path)
        assert result.returncode == 0, (command, result.stderr)
    new_file = datasets / "q.v2.jsonl"
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(new_file)}}
    assert _run("pre_tool_guard.py", payload, env=env).returncode == 0


def test_pretool_blocks_commit_message_file_with_trailer(tmp_path: Path) -> None:
    msg = tmp_path / "msg.txt"
    msg.write_text("feat: x\n\n" + TRAILER + ": A <a@b.c>\n")
    assert _bash(f"git commit -F {msg}").returncode == 2
    msg.write_text("feat: x\n")
    assert _bash(f"git commit -F {msg}").returncode == 0


def test_pretool_survives_garbage_input() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "pre_tool_guard.py")],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0


def test_post_edit_format_formats_python(tmp_path: Path) -> None:
    target = tmp_path / "ugly.py"
    target.write_text("x=1\ny = [1,2,\n3]\n")
    result = _run("post_edit_format.py", {"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert result.returncode == 0
    assert target.read_text() == "x = 1\ny = [1, 2, 3]\n"


def test_post_edit_format_noop_for_unknown_files(tmp_path: Path) -> None:
    target = tmp_path / "notes.bin"
    target.write_bytes(b"\x00\x01")
    result = _run("post_edit_format.py", {"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert result.returncode == 0
    assert target.read_bytes() == b"\x00\x01"


def test_stop_check_honours_stop_hook_active() -> None:
    result = _run("stop_check.py", {"stop_hook_active": True}, env={"CRAG_STOP_CHECK_CMD": "false"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_stop_check_blocks_once_on_failure() -> None:
    result = _run("stop_check.py", {"stop_hook_active": False}, env={"CRAG_STOP_CHECK_CMD": "false"})
    assert result.returncode == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"


def test_stop_check_passes_when_green() -> None:
    result = _run("stop_check.py", {"stop_hook_active": False}, env={"CRAG_STOP_CHECK_CMD": "true"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_session_start_is_noop_locally() -> None:
    proc = subprocess.run(
        ["bash", str(HOOKS / "session_start.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CODE_REMOTE": "false"},
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert "skipping" in proc.stdout


def test_session_start_is_idempotent_shell() -> None:
    text = (HOOKS / "session_start.sh").read_text()
    assert "CLAUDE_CODE_REMOTE" in text and "docker info" in text
    assert "set -u" in text
