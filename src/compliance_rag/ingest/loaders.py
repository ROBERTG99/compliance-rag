"""Source loaders (FR-2): LangChain loaders behind magic-byte, page-count and zip-bomb guards."""

from __future__ import annotations

import io
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

MAX_PDF_PAGES = 500
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_DOCX_RATIO = 100
FORMATS = ("pdf", "docx", "html", "md")


class UnsupportedDocument(ValueError):
    """The bytes do not match the declared format or exceed a safety limit."""


def sniff_format(blob: bytes, declared: str) -> None:
    head = blob[:1024]
    if declared == "pdf":
        if not head.startswith(b"%PDF-"):
            raise UnsupportedDocument("not a PDF (missing %PDF- header)")
    elif declared == "docx":
        if not head.startswith(b"PK\x03\x04"):
            raise UnsupportedDocument("not a DOCX (not a zip container)")
        _check_docx(blob)
    elif declared in {"html", "md"}:
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedDocument(f"{declared} must be UTF-8 text") from exc
        if "\x00" in text:
            raise UnsupportedDocument(f"{declared} contains NUL bytes")
        if declared == "html" and "<" not in text[:2048]:
            raise UnsupportedDocument("html has no markup")
    else:
        raise UnsupportedDocument(f"unsupported format {declared!r}")


def _check_docx(blob: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            names = {i.filename for i in infos}
            if "word/document.xml" not in names:
                raise UnsupportedDocument("zip is not a Word document")
            total = sum(i.file_size for i in infos)
            compressed = max(1, sum(i.compress_size for i in infos))
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocument("corrupt DOCX") from exc
    if total > MAX_DOCX_UNCOMPRESSED or total / compressed > MAX_DOCX_RATIO:
        raise UnsupportedDocument("DOCX expands too much (zip-bomb guard)")


def _with_tempfile(blob: bytes, suffix: str, fn: Callable[[str], str]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"source{suffix}"
        path.write_bytes(blob)
        return fn(str(path))


def _load_pdf(path: str) -> str:
    from langchain_community.document_loaders import PyPDFLoader
    from pypdf import PdfReader

    if len(PdfReader(path).pages) > MAX_PDF_PAGES:
        raise UnsupportedDocument(f"PDF has more than {MAX_PDF_PAGES} pages")
    return "\n".join(doc.page_content for doc in PyPDFLoader(path, mode="page").load())


def _load_docx(path: str) -> str:
    from langchain_community.document_loaders import Docx2txtLoader

    return "\n".join(doc.page_content for doc in Docx2txtLoader(path).load())


def _load_html(path: str) -> str:
    from langchain_community.document_loaders import BSHTMLLoader

    return "\n".join(doc.page_content for doc in BSHTMLLoader(path, open_encoding="utf-8").load())


def extract_text(blob: bytes, fmt: str) -> str:
    """Return the extracted text that chunk offsets refer to."""
    sniff_format(blob, fmt)
    if fmt == "md":
        text = blob.decode("utf-8")
    elif fmt == "pdf":
        text = _with_tempfile(blob, ".pdf", _load_pdf)
    elif fmt == "docx":
        text = _with_tempfile(blob, ".docx", _load_docx)
    else:
        text = _with_tempfile(blob, ".html", _load_html)
    return text.replace("\r\n", "\n").replace("\r", "\n")
