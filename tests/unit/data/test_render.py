"""Every source format parses back to text containing the facts."""

import io
import re
import unicodedata

import docx2txt
import pytest
from bs4 import BeautifulSoup
from pypdf import PdfReader

from data.generator.corpus import SEED, build_corpus
from data.generator.injections import CANARY_PATTERN
from data.generator.render import render_version


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _extract(fmt: str, blob: bytes) -> str:
    if fmt == "md":
        return blob.decode()
    if fmt == "html":
        return BeautifulSoup(blob, "html.parser").get_text("\n")
    if fmt == "docx":
        return docx2txt.process(io.BytesIO(blob))
    if fmt == "pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(blob)).pages)
    raise AssertionError(fmt)


@pytest.mark.parametrize("fmt", ["md", "html", "docx", "pdf"])
def test_every_format_roundtrips_facts(fmt: str) -> None:
    policies = build_corpus(SEED)
    sample = [p for p in policies if p.product][:3] + [p for p in policies if p.document_id == "KYC-0042"]
    for policy in sample:
        version = policy.current
        blob = render_version(policy, version, fmt)
        text = _norm(_extract(fmt, blob))
        for fact in version.facts:
            assert _norm(fact.statement) in text, (fmt, policy.document_id, fact.statement)
        assert re.search(r"Article 1\b", text)
        assert re.search(rf"Article {len(version.articles)}\b", text)


def test_rendering_is_byte_stable() -> None:
    policy = build_corpus(SEED)[0]
    for fmt in ("md", "html", "docx", "pdf"):
        assert render_version(policy, policy.current, fmt) == render_version(policy, policy.current, fmt), fmt


def test_thirty_canary_documents() -> None:
    policies = build_corpus(SEED)
    injected = [p for p in policies if any(v.injection for v in p.versions)]
    assert len(injected) == 30
    canaries = set()
    for p in injected:
        for v in p.versions:
            if v.injection:
                assert CANARY_PATTERN.fullmatch(v.injection["canary"])
                body = " ".join(par for a in v.articles for par in a.paragraphs)
                assert v.injection["canary"] in body
                canaries.add(v.injection["canary"])
    assert len(canaries) == 30
    assert not any(p.document_id in {"KYC-0042", "AML-0107", "CMP-0215"} for p in injected)
