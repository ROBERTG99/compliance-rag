"""``evalgate`` CLI (vendored subset): run, check, report, calibrate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from evalgate.calibrate import calibrate as do_calibrate
from evalgate.check import check as do_check
from evalgate.report import render_markdown
from evalgate.runner import run_suite
from evalgate.suite import load_suite, resolve

app = typer.Typer(add_completion=False, help="Evaluation gate: run suites, check thresholds and baselines.")


@app.command()
def run(
    suite: Path,
    split: str = typer.Option("test", help="dataset split: dev, test or all"),
    out: Path = typer.Option(..., help="report JSON path"),
    limit: int = typer.Option(0, help="first N cases only (smoke runs)"),
) -> None:
    report = asyncio.run(run_suite(load_suite(suite), split, limit=limit or None))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    typer.echo(f"{report['suite']}: {'PASS' if report['passed'] else 'FAIL'} → {out}")


@app.command()
def check(
    reports: list[Path],
    baseline: Path | None = typer.Option(None, help="baseline report (or combined baseline) JSON"),
    max_regression_pp: float = typer.Option(1.0, "--max-regression-pp"),
) -> None:
    base = json.loads(baseline.read_text()) if baseline and baseline.exists() else {}
    failures: list[str] = []
    for path in reports:
        report = json.loads(path.read_text())
        suite_base = base.get(report["suite"], base if base.get("suite") == report["suite"] else None)
        failures += [f"[{report['suite']}] {f}" for f in do_check(report, suite_base, max_regression_pp)]
    for f in failures:
        typer.echo(f"FAIL {f}", err=True)
    if failures:
        raise typer.Exit(1)
    typer.echo("all gates pass")


@app.command()
def report(
    reports: list[Path],
    md: Path = typer.Option(..., help="markdown output"),
    title: str = typer.Option("Evaluation report"),
    preface: Path | None = typer.Option(None, help="markdown file prepended under the title"),
) -> None:
    loaded = [json.loads(p.read_text()) for p in reports]
    text = render_markdown(loaded, title=title, preface=preface.read_text() if preface else "")
    md.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {md}")


@app.command()
def calibrate(
    rubric: Path = typer.Option(..., help="rubric YAML (judge, min_agreement)"),
    labels: Path = typer.Option(..., help="labelled answers JSONL"),
) -> None:
    import yaml

    spec = yaml.safe_load(rubric.read_text())
    judge = resolve(spec.get("judge", "evalgate.testing:FakeJudge"))()
    result = do_calibrate(labels, judge)
    typer.echo(f"agreement {result['agreement']:.3f} on {result['n']} labels (min {spec['min_agreement']})")
    for d in result["disagreements"][:10]:
        typer.echo(f"  disagree {d['id']}: label={d['label']} reason={d['reason']}")
    if result["agreement"] < float(spec["min_agreement"]):
        raise typer.Exit(1)
