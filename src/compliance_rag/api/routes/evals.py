"""Latest evaluation summary for the Evaluation screen (written by ``scripts/run_evals.py``)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from compliance_rag.api.deps import current_principal, get_state
from compliance_rag.api.errors import not_found
from compliance_rag.api.schemas import EvalsLatest
from compliance_rag.api.state import AppState
from compliance_rag.retrieval.types import Principal

router = APIRouter(prefix="/v1", tags=["evals"])
LATEST = ("evals", "reports", "latest.json")


@router.get("/evals/latest", response_model=EvalsLatest)
async def latest_report(
    principal: Principal = Depends(current_principal), state: AppState = Depends(get_state)
) -> dict[str, Any]:
    path = state.settings.root.joinpath(*LATEST)
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise not_found("evaluation report") from exc
    return data
