"""Claude Code settings, CLAUDE.md and rules (T-04)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ["python", "frontend", "llm-code", "testing", "evals", "docker", "security", "docs", "retrieval"]


def test_attribution_key_kept_and_env_denied() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    assert settings["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}
    perms = settings["permissions"]
    for rule in ["Read(.env)", "Read(.env.*)", "Bash(git push --force*)", "Bash(git push -f*)",
                 "Bash(rm -rf /*)", "Bash(rm -rf ~*)"]:
        assert rule in perms["deny"], rule
    for rule in ["Bash(make *)", "Bash(uv run *)", "Bash(pnpm *)", "Bash(docker compose *)",
                 "Bash(git push -u origin *)", "Bash(crag *)", "Read(.env.example)"]:
        assert rule in perms["allow"], rule
    assert "ask" not in perms or perms["ask"] == []


def test_hooks_registered() -> None:
    hooks = json.loads((ROOT / ".claude/settings.json").read_text())["hooks"]
    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= set(hooks)


def test_claude_md_is_short_and_has_rules() -> None:
    text = (ROOT / "CLAUDE.md").read_text()
    assert len(text.splitlines()) < 200
    for needle in ["Co-Authored-By", "PROGRESS.md", "docs/DECISIONS.md", "gateway", "Principal"]:
        assert needle in text, needle
    assert (ROOT / "AGENTS.md").is_file()


def test_rules_have_paths_frontmatter() -> None:
    for name in RULES:
        text = (ROOT / f".claude/rules/{name}.md").read_text()
        assert text.startswith("---\npaths:"), name
    assert not (ROOT / ".claude/rules/git-commits.md").read_text().startswith("---")
