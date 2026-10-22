"""Subagents and skills exist with complete frontmatter."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AGENTS = [
    "reviewer",
    "security-auditor",
    "test-designer",
    "eval-analyst",
    "ux-reviewer",
    "docs-editor",
    "retrieval-reviewer",
    "acl-auditor",
]
SKILLS = [
    "tdd",
    "quality-gate",
    "eval-report",
    "new-adr",
    "add-migration",
    "add-endpoint",
    "add-retrieval-leg",
    "add-eval-case",
    "demo-capture",
    "release",
    "add-corpus-domain",
    "run-ablation",
    "debug-retrieval",
]


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text()
    assert text.startswith("---\n"), path
    _, block, body = text.split("---\n", 2)
    assert body.strip(), f"{path} has no body"
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    return data


def test_frontmatter_complete() -> None:
    for name in AGENTS:
        meta = _frontmatter(ROOT / ".claude" / "agents" / f"{name}.md")
        for key in ("name", "description", "tools", "model"):
            assert meta.get(key), (name, key)
        assert meta["name"] == name


def test_reviewer_is_read_only_with_verdict() -> None:
    path = ROOT / ".claude" / "agents" / "reviewer.md"
    meta = _frontmatter(path)
    tools = str(meta["tools"])
    assert "Write" not in tools and "Edit" not in tools
    body = path.read_text()
    assert '"approve"' in body and '"changes requested"' in body


def test_skills_exist() -> None:
    for name in SKILLS:
        meta = _frontmatter(ROOT / ".claude" / "skills" / name / "SKILL.md")
        assert meta.get("name") == name
        assert meta.get("description")
