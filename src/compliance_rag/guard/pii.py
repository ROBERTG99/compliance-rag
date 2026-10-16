"""PII redaction applied by the LLM gateway before any provider call."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_CARD = re.compile(r"\b\d{4}(?:[ -]?\d{4}){2,3}\b|\b\d{13,19}\b")
_PHONE = re.compile(
    r"(?<![\w-])\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}\b|\b\(\d{2,4}\)[ .-]?\d{3,4}[ .-]?\d{3,4}\b"
)
_ACCOUNT = re.compile(r"\b\d{10,}\b")


def redact(text: str) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _IBAN.sub("[ACCOUNT]", text)
    text = _CARD.sub("[ACCOUNT]", text)
    text = _PHONE.sub("[PHONE]", text)
    return _ACCOUNT.sub("[ACCOUNT]", text)
