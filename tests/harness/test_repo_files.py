"""Repository scaffolding checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_files_exist() -> None:
    for rel in [
        "docs/DEVELOPMENT.md",
        ".gitignore",
        ".editorconfig",
        "docs/DECISIONS.md",
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
    rule = (ROOT / ".claude/rules/git-commits.md").read_text()
    assert not rule.startswith("---"), "git-commits rule must have no frontmatter"


def test_integrations_present() -> None:
    import json

    import yaml

    for rel in [
        ".pre-commit-config.yaml",
        ".github/dependabot.yml",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/CODEOWNERS",
        ".devcontainer/devcontainer.json",
        ".mcp.json",
        ".markdownlint-cli2.yaml",
    ]:
        assert (ROOT / rel).is_file(), rel
    assert "* @ROBERTG99" in (ROOT / ".github/CODEOWNERS").read_text()
    ecosystems = {
        u["package-ecosystem"]
        for u in yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())["updates"]
    }
    assert {"pip", "npm", "docker", "github-actions"} <= ecosystems
    hooks = {
        h["id"]
        for r in yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())["repos"]
        for h in r["hooks"]
    }
    assert {"ruff", "ruff-format", "prettier", "gitleaks", "markdownlint"} <= hooks
    servers = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert {"playwright", "postgres"} <= set(servers)
    template = (ROOT / ".github/pull_request_template.md").read_text()
    assert "Co-Authored-By" not in template
