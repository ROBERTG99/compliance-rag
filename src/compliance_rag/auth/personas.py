"""Roles, groups and the four dev personas."""

from __future__ import annotations

from compliance_rag.retrieval.types import Principal, Role

ROLE_GROUPS: dict[str, list[str]] = {
    "analyst": ["compliance", "all"],
    "legal": ["legal", "compliance", "all"],
    "support": ["support", "all"],
    "content_admin": ["compliance", "all"],
}

PERSONAS: dict[str, tuple[str, Role]] = {
    "analyst": ("analyst@northwind.test", "analyst"),
    "legal": ("legal@northwind.test", "legal"),
    "support": ("support@northwind.test", "support"),
    "content_admin": ("admin@northwind.test", "content_admin"),
    "admin": ("admin@northwind.test", "content_admin"),
}


def persona_principal(persona: str) -> Principal:
    sub, role = PERSONAS[persona]
    return {"sub": sub, "role": role, "groups": list(ROLE_GROUPS[role])}
