"""Write the generated corpus to disk: model JSON, rendered sources and a manifest with a stable hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from data.generator.corpus import (
    CORPUS_VERSION,
    SEED,
    Policy,
    build_corpus,
    corpus_fingerprint,
    policy_to_dict,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_corpus(out_dir: Path, seed: int = SEED, render: bool = True) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    policies: list[Policy] = build_corpus(seed)
    files: dict[str, str] = {}
    if render:
        from data.generator.render import render_policy

        for policy in policies:
            for rel, blob in render_policy(policy).items():
                target = out_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
                files[rel] = hashlib.sha256(blob).hexdigest()
    (out_dir / "corpus.json").write_text(_canonical([policy_to_dict(p) for p in policies]))
    manifest: dict[str, Any] = {
        "corpus_version": CORPUS_VERSION,
        "seed": seed,
        "n_policies": len(policies),
        "n_versions": sum(len(p.versions) for p in policies),
        "model_fingerprint": corpus_fingerprint(policies),
        "files": files,
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical(manifest).encode()).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
