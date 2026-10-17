"""Write the OpenAPI document (``make docs``): ``python scripts/export_openapi.py docs/openapi.json``.

Building the schema needs no running services; the CI check compares this output with the committed file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from compliance_rag.api.app import create_app
from compliance_rag.settings import Settings


def render() -> str:
    app = create_app(Settings(_env_file=None))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    out = Path(argv[1] if len(argv) > 1 else "docs/openapi.json")
    text = render()
    if "--check" in argv:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"{out} is stale: run `make docs`", file=sys.stderr)
            return 1
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
