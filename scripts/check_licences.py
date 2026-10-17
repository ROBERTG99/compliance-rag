"""Licence check for `make security`: runtime dependencies must use a permissive or weak-copyleft licence.

Python: every installed distribution (pip-licenses); web: production dependencies (pnpm). Strong copyleft
(GPL, AGPL, SSPL) and unknown licences fail unless listed in OVERRIDES with the verified licence.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

ALLOWED = re.compile(
    r"MIT|BSD|Apache|ISC|PSF|Python Software Foundation|MPL|Mozilla Public|LGPL|ZPL|Unlicense|0BSD|CC0|Zlib|OFL|"
    r"DFSG approved|HPND",
    re.I,
)
DENIED = re.compile(r"(?<!L)GPL|AGPL|SSPL|Commons Clause|BUSL", re.I)
# verified by hand: the metadata carries no licence classifier
OVERRIDES = {"docx2txt": "MIT (https://github.com/ankushshah89/python-docx2txt/blob/master/LICENSE.txt)"}


def problems(name: str, licence: str) -> str | None:
    if name in OVERRIDES:
        return None
    if DENIED.search(licence) or not ALLOWED.search(licence):
        return f"{name}: {licence}"
    return None


def python_packages() -> list[tuple[str, str]]:
    out = subprocess.run(["pip-licenses", "--format=json"], check=True, capture_output=True, text=True).stdout
    return [(p["Name"], p["License"]) for p in json.loads(out)]


def web_packages() -> list[tuple[str, str]]:
    out = subprocess.run(
        ["pnpm", "-C", "web", "licenses", "list", "--prod", "--json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [(pkg["name"], licence) for licence, pkgs in json.loads(out).items() for pkg in pkgs]


def main() -> int:
    found = [p for name, lic in python_packages() + web_packages() if (p := problems(name, lic))]
    for p in found:
        print(f"licence not allowed: {p}", file=sys.stderr)
    print("licences ok" if not found else f"{len(found)} licence problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
