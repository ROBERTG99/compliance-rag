"""The single source of retrieval filters: ACL groups, validity at ``as_of`` and visibility.

Every backend builds its query predicate from :class:`AccessFilter`, so the principal's groups are
always inside the query (never a post-filter). Validity is ``valid_from <= as_of < valid_to``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from compliance_rag.retrieval.types import Principal

OPEN_END = 99_999_999  # integer stand-in for "no valid_to" in Qdrant payloads


@dataclass(frozen=True)
class AccessFilter:
    groups: tuple[str, ...]
    as_of: date

    @classmethod
    def for_principal(cls, principal: Principal, as_of: date) -> AccessFilter:
        groups = tuple(sorted({g for g in principal["groups"] if g}))
        if not groups:
            raise PermissionError("principal has no groups")
        return cls(groups=groups, as_of=as_of)

    # --- Postgres (pgvector) -------------------------------------------------------------
    SQL = "c.visible AND c.acl_groups && %(groups)s::text[] AND c.valid_from <= %(as_of)s AND (c.valid_to IS NULL OR c.valid_to > %(as_of)s)"

    def sql_params(self) -> dict[str, Any]:
        return {"groups": list(self.groups), "as_of": self.as_of}

    # --- OpenSearch ------------------------------------------------------------------------
    def opensearch(self) -> list[dict[str, Any]]:
        day = self.as_of.isoformat()
        return [
            {"terms": {"acl_groups": list(self.groups)}},
            {"term": {"visible": True}},
            {"range": {"valid_from": {"lte": day}}},
            {
                "bool": {
                    "should": [
                        {"bool": {"must_not": {"exists": {"field": "valid_to"}}}},
                        {"range": {"valid_to": {"gt": day}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        ]

    # --- Qdrant ----------------------------------------------------------------------------
    def qdrant(self) -> Any:
        from qdrant_client import models

        day = date_to_int(self.as_of)
        return models.Filter(
            must=[
                models.FieldCondition(key="acl_groups", match=models.MatchAny(any=list(self.groups))),
                models.FieldCondition(key="visible", match=models.MatchValue(value=True)),
                models.FieldCondition(key="valid_from_n", range=models.Range(lte=day)),
                models.FieldCondition(key="valid_to_n", range=models.Range(gt=day)),
            ]
        )

    def allows(self, acl_groups: list[str], valid_from: str, valid_to: str | None) -> bool:
        """Post-check used to count violations (``crag_acl_postcheck_violations_total``)."""
        day = self.as_of.isoformat()
        return (
            bool(set(acl_groups) & set(self.groups))
            and valid_from <= day
            and (valid_to is None or day < valid_to)
        )


def date_to_int(day: date | None) -> int:
    return OPEN_END if day is None else day.year * 10000 + day.month * 100 + day.day
