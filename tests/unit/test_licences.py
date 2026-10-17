"""The licence gate allows permissive and weak-copyleft licences only (make security)."""

from __future__ import annotations

from scripts.check_licences import problems


def test_permissive_and_weak_copyleft_pass() -> None:
    for licence in ("MIT", "Apache-2.0", "BSD-3-Clause", "LGPL-3.0-only", "MPL-2.0", "OFL-1.1", "PSF-2.0"):
        assert problems("pkg", licence) is None, licence


def test_strong_copyleft_and_unknown_fail() -> None:
    for licence in (
        "GPL-3.0-only",
        "AGPL-3.0",
        "SSPL-1.0",
        "UNKNOWN",
        "GNU General Public License v3 (GPLv3)",
    ):
        assert problems("pkg", licence) is not None, licence
    assert problems("docx2txt", "UNKNOWN") is None  # verified override
