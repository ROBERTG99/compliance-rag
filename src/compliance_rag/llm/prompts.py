"""Versioned prompt files (``prompts/<name>.v<N>.md``) and their hashes."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from compliance_rag.settings import get_settings


def prompts_dir() -> Path:
    root = get_settings().root / "prompts"
    if root.is_dir():
        return root
    return Path(__file__).resolve().parents[3] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str, version: str = "v1") -> str:
    return (prompts_dir() / f"{name}.{version}.md").read_text(encoding="utf-8")


def prompt_hash(name: str, version: str = "v1") -> str:
    return hashlib.sha256(load_prompt(name, version).encode()).hexdigest()


def prompt_hashes() -> dict[str, str]:
    return {
        f"{p.stem}": hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(prompts_dir().glob("*.md"))
    }
