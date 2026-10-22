"""Provider SDKs are imported only by the LLM gateway."""

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


BEDROCK_CLIENT = re.compile(r"""client\(\s*(?:service_name\s*=\s*)?["']bedrock(?:-runtime)?["']""")


def test_the_bedrock_pattern_covers_both_call_forms() -> None:
    assert BEDROCK_CLIENT.search('boto3.client("bedrock-runtime", region_name=r)')
    assert BEDROCK_CLIENT.search("session.client(service_name='bedrock-runtime')")
    assert not BEDROCK_CLIENT.search('boto3.client("s3")')


def test_only_gateway_creates_bedrock_runtime_clients() -> None:
    # boto3 is also the S3 client, so the import contract cannot fence Bedrock off; the client call can be
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if BEDROCK_CLIENT.search(p.read_text()) and p.name != "gateway.py"
    ]
    assert offenders == []
    assert BEDROCK_CLIENT.search(
        (ROOT / "src/compliance_rag/llm/gateway.py").read_text()
    )  # the pattern still matches
