"""Provider SDKs are imported only by the LLM gateway (BUILD.md Appendix B)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_IMPORT = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.M)


def test_only_gateway_imports_provider_sdks() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if PROVIDER_IMPORT.search(p.read_text()) and p.name != "gateway.py"
    ]
    assert offenders == []


def test_import_linter_contract_passes() -> None:
    proc = subprocess.run(
        ["uv", "run", "lint-imports", "--no-cache"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
