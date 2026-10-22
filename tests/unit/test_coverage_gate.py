"""Coverage gate for `make test`: ≥ 85% lines per core package, ≥ 70% overall."""

from __future__ import annotations

from pathlib import Path

from scripts.check_coverage import check

CORE = ("graph", "retrieval", "rerank", "guard", "auth", "ingest")


def _cls(filename: str, lines: str) -> str:
    return f'<class filename="{filename}"><lines>{lines}</lines></class>'


def _lines(hit: int, miss: int) -> str:
    rows = [f'<line number="{i}" hits="1"/>' for i in range(hit)]
    rows += [f'<line number="{hit + i}" hits="0"/>' for i in range(miss)]
    return "".join(rows)


def _write(tmp_path: Path, graph: tuple[int, int], api: tuple[int, int]) -> Path:
    """`graph` hit/miss for every core package (graph itself as given), `api` for a non-core package."""
    classes = [_cls(f"src/compliance_rag/{pkg}/mod.py", _lines(*graph)) for pkg in CORE]
    classes.append(_cls("src/compliance_rag/api/routes/ask.py", _lines(*api)))
    path = tmp_path / "coverage.xml"
    path.write_text(
        f"<coverage><packages><package><classes>{''.join(classes)}</classes></package></packages></coverage>"
    )
    return path


def test_core_package_below_85_fails_even_when_overall_passes(tmp_path: Path) -> None:
    failures = check(_write(tmp_path, graph=(84, 16), api=(100, 0)))
    assert any("graph" in f and "84.0%" in f for f in failures)


def test_overall_below_70_fails(tmp_path: Path) -> None:
    failures = check(_write(tmp_path, graph=(86, 14), api=(0, 2000)))
    assert any(f.startswith("overall") for f in failures)


def test_a_core_package_missing_from_the_report_fails(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text("<coverage><packages/></coverage>")
    assert any(f.startswith("graph") for f in check(path))


def test_passing_report(tmp_path: Path) -> None:
    assert check(_write(tmp_path, graph=(90, 10), api=(70, 30))) == []
