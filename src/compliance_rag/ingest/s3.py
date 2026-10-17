"""S3 inbox: ``inbox/<name>.<ext>`` plus a sidecar ``inbox/<name>.json`` with the document metadata.

``poll_inbox`` (Arq cron every 30 s) registers each complete pair, enqueues its ingest job and moves both
objects to ``processed/`` (or ``failed/`` with an error note). Identical bytes are idempotent anyway.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from compliance_rag.ingest.pipeline import (
    MAX_UPLOAD_BYTES,
    DocumentMeta,
    IngestDeps,
    RegisteredJob,
    register_upload,
)
from compliance_rag.validation import DOCUMENT_ID_PATTERN, Domain, Group, IsoDate, SafeText

log = structlog.get_logger(__name__)
INBOX = "inbox/"
FORMAT_BY_EXT = {"pdf": "pdf", "docx": "docx", "html": "html", "htm": "html", "md": "md", "markdown": "md"}


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern=DOCUMENT_ID_PATTERN)
    version: int = Field(ge=1)
    title: SafeText = Field(min_length=1, max_length=300)
    domain: Domain
    owner: SafeText = Field(min_length=1, max_length=120)
    valid_from: IsoDate
    valid_to: IsoDate | None = None
    acl_groups: list[Group] = Field(min_length=1)

    @field_validator("acl_groups", mode="before")
    @classmethod
    def _split(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [g.strip() for g in value.split(",") if g.strip()]
        return value

    @field_validator("acl_groups")
    @classmethod
    def _groups(cls, value: list[Group]) -> list[Group]:
        return sorted(set(value))

    def to_meta(self, source_format: str) -> DocumentMeta:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return DocumentMeta(
            self.document_id,
            self.version,
            self.title,
            self.domain,
            self.owner,
            self.valid_from,
            source_format,
            [str(g) for g in self.acl_groups],
            self.valid_to,
        )


def format_for(name: str) -> str | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return FORMAT_BY_EXT.get(ext)


@dataclass
class PollResult:
    registered: int
    failed: int
    waiting: int


async def _move(deps: IngestDeps, key: str, prefix: str) -> None:
    blob = await deps.objects.get(key)
    await deps.objects.put(prefix + key.removeprefix(INBOX), blob)
    await deps.objects.delete(key)


async def poll_inbox(
    deps: IngestDeps, enqueue: Callable[[RegisteredJob], Any], requested_by: str = "s3-inbox"
) -> PollResult:
    keys = set(await deps.objects.list(INBOX))
    registered = failed = waiting = 0
    for key in sorted(keys):
        if key.endswith(".json") or format_for(key) is None:
            continue
        sidecar = key.rsplit(".", 1)[0] + ".json"
        if sidecar not in keys:
            waiting += 1
            continue
        try:
            meta = DocumentMetadata.model_validate(json.loads(await deps.objects.get(sidecar)))
            if await deps.objects.size(key) > MAX_UPLOAD_BYTES:  # HEAD: never download an oversized file
                raise ValueError(f"file exceeds {MAX_UPLOAD_BYTES} bytes")
            job = await register_upload(
                deps,
                meta.to_meta(format_for(key) or "md"),
                await deps.objects.get(key),
                requested_by,
                actor_role="system",  # inbox uploads are audited like API uploads
            )
        except (ValidationError, ValueError, json.JSONDecodeError, psycopg.errors.IntegrityError) as exc:
            # the file itself is wrong: park it with the reason so it never blocks the inbox again
            await deps.objects.put(f"failed/{key.removeprefix(INBOX)}.error.txt", str(exc)[:2000].encode())
            failed += 1
            await _move(deps, key, "failed/")
            await _move(deps, sidecar, "failed/")
            continue
        except Exception as exc:  # infrastructure (database, storage): leave it for the next poll
            log.warning("inbox_item_deferred", key=key, error=type(exc).__name__)
            continue
        try:
            outcome = enqueue(job)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as exc:  # queue down: registration is idempotent, so the next poll re-enqueues it
            log.warning("inbox_enqueue_deferred", key=key, error=type(exc).__name__)
            continue
        registered += 1
        target = "processed/"
        await _move(deps, key, target)
        await _move(deps, sidecar, target)
    return PollResult(registered, failed, waiting)
