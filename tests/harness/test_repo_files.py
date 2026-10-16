"""Repository scaffolding checks (T-01, T-07)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_files_exist() -> None:
    for rel in [
        "docs/DEVELOPMENT.md",
        ".gitignore",
        ".editorconfig",
        "PROGRESS.md",
        "docs/DECISIONS.md",
        "docs/specs/000-build-spec.md",
        "LICENSE",
        ".claude/settings.json",
        ".claude/rules/git-commits.md",
    ]:
        assert (ROOT / rel).is_file(), rel
    ignore = (ROOT / ".gitignore").read_text()
    for pattern in [
        ".env",
        ".env.*",
        "!.env.example",
        ".venv/",
        "node_modules/",
        "web/dist/",
        "data/generated/",
        "evals/reports/runs/",
        "playwright-report/",
    ]:
        assert pattern in ignore.splitlines(), pattern
    assert "ROBERTG99" in (ROOT / "LICENSE").read_text()
    progress = (ROOT / "PROGRESS.md").read_text()
    assert progress.startswith("# PROGRESS") and "## Needs the maintainer" in progress
    assert "T-51" in progress
    rule = (ROOT / ".claude/rules/git-commits.md").read_text()
    assert not rule.startswith("---"), "git-commits rule must have no frontmatter"
