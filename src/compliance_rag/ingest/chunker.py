"""Heading/article-aware chunker (FR-2).

Sections start at ``Article N — Heading`` lines (Markdown ``#`` prefixes and ``-``/``—`` dashes are
accepted); text before the first article is the preamble. A section of at most ``MAX_TOKENS``
becomes one chunk; longer sections are split *within* the section by LangChain's
``RecursiveCharacterTextSplitter``. Offsets always satisfy ``text == extracted[char_start:char_end]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

MIN_TOKENS = 300
MAX_TOKENS = 800
TARGET_SPLIT_TOKENS = 600
TOKEN_RE = re.compile(r"\w+|[^\w\s]")
HEADING_RE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*)?Article[ \t]+(\d+)[ \t]*[—–-][ \t]*(.+?)[ \t]*$", re.M)


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    section_path: str
    text: str
    char_start: int
    char_end: int
    token_count: int


def count_tokens(text: str) -> int:
    """Deterministic word/punctuation token estimate (no network-downloaded BPE files)."""
    return len(TOKEN_RE.findall(text))


def _sections(text: str) -> list[tuple[str, int, int]]:
    matches = list(HEADING_RE.finditer(text))
    sections: list[tuple[str, int, int]] = []
    first = matches[0].start() if matches else len(text)
    if text[:first].strip():
        sections.append(("Preamble", 0, first))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((f"Article {m.group(1)} — {m.group(2).strip()}", m.start(), end))
    return sections


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


_splitter = RecursiveCharacterTextSplitter(
    chunk_size=TARGET_SPLIT_TOKENS,
    chunk_overlap=0,
    length_function=count_tokens,
    separators=["\n\n", "\n", ". ", " ", ""],
    keep_separator="end",
    add_start_index=True,
    strip_whitespace=True,
)


def _split_section(text: str, start: int, end: int) -> list[tuple[int, int]]:
    body = text[start:end]
    pieces: list[tuple[int, int]] = []
    cursor = 0
    for doc in _splitter.create_documents([body]):
        piece = doc.page_content
        idx = body.find(piece, cursor)
        if idx < 0:  # pragma: no cover - splitter guarantees substrings
            idx = int(doc.metadata.get("start_index", cursor))
        s, e = _trim(text, start + idx, start + idx + len(piece))
        if e > s:
            pieces.append((s, e))
        cursor = idx + len(piece)
    # any residual piece still above the cap is cut hard on token boundaries
    out: list[tuple[int, int]] = []
    for s, e in pieces:
        while count_tokens(text[s:e]) > MAX_TOKENS:
            tokens = list(TOKEN_RE.finditer(text, s, e))
            cut = tokens[MAX_TOKENS - 1].end()
            out.append(_trim(text, s, cut))
            s, e = _trim(text, cut, e)
        if e > s:
            out.append((s, e))
    return out


def chunk_text(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, sec_start, sec_end in _sections(text):
        start, end = _trim(text, sec_start, sec_end)
        if end <= start:
            continue
        spans = (
            [(start, end)]
            if count_tokens(text[start:end]) <= MAX_TOKENS
            else _split_section(text, start, end)
        )
        for s, e in spans:
            tokens = count_tokens(text[s:e])
            if tokens == 0:
                continue
            chunks.append(Chunk(len(chunks), path, text[s:e], s, e, tokens))
    return chunks
