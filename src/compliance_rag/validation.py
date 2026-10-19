"""Shared request types so the OpenAPI contract states what the API actually accepts."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal, get_args

from pydantic import AfterValidator, BeforeValidator

Domain = Literal["aml", "complaints", "kyc", "limits", "retention", "vendors"]
Group = Literal["all", "compliance", "legal", "support"]
DOMAINS: frozenset[str] = frozenset(get_args(Domain))
GROUPS: frozenset[str] = frozenset(get_args(Group))
GROUP_LIST_PATTERN = r"^\s*(all|compliance|legal|support)\s*(,\s*(all|compliance|legal|support)\s*)*$"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_date(value: Any) -> Any:
    # Pydantic's lax mode would read 0 or "0" as a Unix timestamp; the contract says YYYY-MM-DD
    if isinstance(value, date) or (isinstance(value, str) and _ISO_DATE.fullmatch(value)):
        return value
    raise ValueError("expected an ISO 8601 date (YYYY-MM-DD)")


IsoDate = Annotated[date, BeforeValidator(_iso_date)]


def no_nul(value: str) -> str:
    # PostgreSQL text cannot hold NUL; reject it as a validation error instead of a 500
    if "\x00" in value:
        raise ValueError("text must not contain NUL characters")
    return value


SafeText = Annotated[str, AfterValidator(no_nul)]
DOCUMENT_ID_PATTERN = r"^[A-Z]{2,4}-[0-9]{4}$"
JobStatus = Literal["queued", "parsing", "embedding", "indexing", "activating", "done", "failed"]
JobKind = Literal["ingest", "acl_sync", "reindex"]
