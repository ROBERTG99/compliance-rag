"""VectorStore protocol. There is deliberately no search method without a Principal."""

from __future__ import annotations

from datetime import date
from typing import Protocol

import numpy as np
import numpy.typing as npt

from compliance_rag.retrieval.types import Candidate, ChunkRecord, Principal


class VectorStore(Protocol):
    name: str

    async def upsert(self, records: list[ChunkRecord]) -> None: ...

    async def search(
        self, embedding: npt.NDArray[np.float32], principal: Principal, as_of: date, k: int
    ) -> list[Candidate]: ...

    async def set_visible(self, version_id: str, visible: bool) -> None: ...

    async def close_version(self, version_id: str, valid_to: date) -> None: ...

    async def update_acl(self, document_id: str, groups: list[str]) -> None: ...

    async def delete_version(self, version_id: str) -> None: ...
