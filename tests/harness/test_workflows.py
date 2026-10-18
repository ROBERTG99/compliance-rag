"""CI workflows of BUILD.md §17 exist with their jobs; actionlint runs in `make security` (T-48)."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict:  # type: ignore[type-arg]
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the `on` key as a boolean
    return dict(data)


def test_the_six_workflows_and_no_terraform() -> None:
    names = {p.name for p in WORKFLOWS.glob("*.yml")}
    assert names == {"ci.yml", "e2e.yml", "evals.yml", "docker.yml", "codeql.yml", "release.yml"}
    for path in WORKFLOWS.glob("*.yml"):
        assert "terraform" not in path.read_text().lower(), path.name


def test_required_checks_run_on_pull_requests_and_call_the_make_targets() -> None:
    expected = {
        "ci.yml": ["make lint", "make typecheck", "make test"],
        "e2e.yml": ["make up", "make demo", "make e2e"],
        "evals.yml": ["make eval", "make redteam"],
        "docker.yml": ["trivy", "--exit-code 1", "HIGH,CRITICAL"],
    }
    for name, needles in expected.items():
        text = (WORKFLOWS / name).read_text()
        assert "pull_request" in _load(name)["on"], name
        for needle in needles:
            assert needle in text, (name, needle)


def test_release_only_on_version_tags_and_least_privilege() -> None:
    release = _load("release.yml")
    assert release["on"] == {"push": {"tags": ["v*"]}}
    for path in WORKFLOWS.glob("*.yml"):
        assert "permissions" in _load(path.name), path.name  # explicit token scopes everywhere
