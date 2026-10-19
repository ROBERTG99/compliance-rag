"""Structure-aware chunking (FR-2, T-15)."""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from compliance_rag.ingest.chunker import MAX_TOKENS, chunk_text, count_tokens
from compliance_rag.ingest.loaders import UnsupportedDocument, extract_text
from data.generator.corpus import Article, Policy, Version
from data.generator.render import render_version

ARTICLE_RE = re.compile(r"Article (\d+)\b")


def _policy(n_articles: int = 12, long_article: int | None = None) -> tuple[Policy, Version]:
    articles = []
    for n in range(1, n_articles + 1):
        paragraphs = [
            f"Paragraph {n}.{k} explains control {n}-{k} for the onboarding process in plain words."
            for k in range(4)
        ]
        if n == long_article:
            paragraphs = [
                " ".join(["This sentence is deliberately long padding text for the splitter."] * 12)
            ] * 12
        articles.append(Article(n, f"Heading {n}", paragraphs))
    version = Version(1, "2025-01-01", None, "md", articles, [])
    return Policy("KYC-0001", "Test Policy", "kyc", "Owner", "Proc", None, ["all"], [version]), version


@pytest.mark.parametrize("fmt", ["md", "html", "docx", "pdf"])
def test_chunks_respect_article_boundaries(fmt: str) -> None:
    policy, version = _policy(12)
    text = extract_text(render_version(policy, version, fmt), fmt)
    chunks = chunk_text(text)
    article_chunks = [c for c in chunks if c.section_path.startswith("Article")]
    assert {int(ARTICLE_RE.match(c.section_path).group(1)) for c in article_chunks} == set(range(1, 13))
    for chunk in chunks:
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        headings = re.findall(r"^(?:#+\s*)?Article (\d+)\b", chunk.text, flags=re.M)
        assert len(headings) <= 1, chunk.section_path  # never crosses an article
        if headings:
            assert chunk.section_path.startswith(f"Article {headings[0]} ")
        assert 1 <= chunk.token_count <= MAX_TOKENS
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_long_article_is_split_within_article() -> None:
    policy, version = _policy(4, long_article=2)
    text = extract_text(render_version(policy, version, "md"), "md")
    chunks = [c for c in chunk_text(text) if c.section_path.startswith("Article 2 ")]
    assert len(chunks) >= 2
    assert all(c.token_count <= MAX_TOKENS for c in chunks)
    assert all(c.text == text[c.char_start : c.char_end] for c in chunks)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.text(alphabet="abcdefghij klmnop.,\n", min_size=0, max_size=1500), st.integers(1, 30)),
        min_size=1,
        max_size=8,
    ),
    st.text(alphabet="xyz \n", max_size=200),
)
def test_offsets_round_trip(sections: list[tuple[str, int]], preamble: str) -> None:
    text = preamble + "".join(
        f"\n## Article {i + 1} — H{n}\n{body}\n" for i, (body, n) in enumerate(sections)
    )
    for chunk in chunk_text(text):
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        assert chunk.char_end > chunk.char_start
        assert 1 <= chunk.token_count <= MAX_TOKENS


def test_count_tokens() -> None:
    assert count_tokens("Hello, world") == 3


def test_magic_bytes_rejected() -> None:
    with pytest.raises(UnsupportedDocument):
        extract_text(b"not a pdf", "pdf")
    with pytest.raises(UnsupportedDocument):
        extract_text(b"%PDF-1.4 fake", "docx")
    with pytest.raises(UnsupportedDocument):
        extract_text(b"\xff\xfe\x00binary", "md")
