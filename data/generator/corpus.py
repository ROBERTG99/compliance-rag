"""Seeded corpus model: 400 policies × 2–4 versions with templated facts, ACLs and validity windows.

``build_corpus(seed)`` is pure and deterministic; rendering to files lives in ``render.py``.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from data.generator.catalog import (
    ARTICLE_HEADINGS,
    DOMAIN_TITLES,
    DOMAINS,
    FACTS,
    FILLER,
    OWNERS,
    PROCESSES,
    PRODUCTS,
    ROLES,
    TENANT,
    TODAY,
    FactTemplate,
)

SEED = 2026
N_POLICIES = 400
CORPUS_VERSION = "corpus.v1"

# ACL mix (groups that may read the document)
ACL_CHOICES: list[tuple[list[str], float]] = [
    (["all"], 0.55),
    (["compliance"], 0.25),
    (["legal"], 0.10),
    (["support", "compliance"], 0.10),
]
FORMAT_CHOICES: list[tuple[str, float]] = [("md", 0.70), ("html", 0.15), ("docx", 0.10), ("pdf", 0.05)]


@dataclass
class Fact:
    key: str
    article: int  # 1-based article number holding the fact
    value: int
    unit: str
    statement: str
    question: str
    numeric: bool


@dataclass
class Article:
    number: int
    heading: str
    paragraphs: list[str]


@dataclass
class Version:
    version: int
    valid_from: str
    valid_to: str | None
    source_format: str
    articles: list[Article]
    facts: list[Fact]
    injection: dict[str, Any] | None = None


@dataclass
class Policy:
    document_id: str
    title: str
    domain: str
    owner: str
    process: str
    product: str | None
    acl_groups: list[str]
    versions: list[Version] = field(default_factory=list)

    def version_at(self, as_of: str) -> Version | None:
        for v in self.versions:
            if v.valid_from <= as_of and (v.valid_to is None or as_of < v.valid_to):
                return v
        return None

    @property
    def current(self) -> Version:
        return self.versions[-1]


def _weighted(rng: random.Random, choices: list[tuple[Any, float]]) -> Any:
    return rng.choices([c for c, _ in choices], weights=[w for _, w in choices], k=1)[0]


def _fmt_value(value: int, unit: str) -> str:
    if unit == "EUR":
        return f"{value:,}"
    return str(value)


def render_fact(template: FactTemplate, product: str, value: int) -> Fact:
    shown = _fmt_value(value, template.unit)
    return Fact(
        key=template.key,
        article=0,
        value=value,
        unit=template.unit,
        statement=template.statement.format(product=product, value=shown),
        question=template.question.format(product=product),
        numeric=template.numeric,
    )


def _paragraphs(rng: random.Random, product: str, process: str, n_par: int) -> list[str]:
    out = []
    for _ in range(n_par):
        sentences = rng.sample(FILLER, k=rng.randint(4, 5))
        out.append(
            " ".join(
                s.format(role=rng.choice(ROLES), product=product, process=process.lower()) for s in sentences
            )
        )
    return out


def _version_dates(rng: random.Random, n_versions: int) -> list[tuple[str, str | None]]:
    start = date(2022, 1, 1) + timedelta(days=rng.randint(0, 540))
    starts = [start]
    for _ in range(n_versions - 1):
        starts.append(starts[-1] + timedelta(days=rng.randint(150, 330)))
    # keep the last version in force today
    today = date.fromisoformat(TODAY)
    while starts[-1] >= today:
        starts = [s - timedelta(days=60) for s in starts]
    out: list[tuple[str, str | None]] = []
    for i, s in enumerate(starts):
        end = starts[i + 1].isoformat() if i + 1 < len(starts) else None
        out.append((s.isoformat(), end))
    return out


def _build_versions(
    rng: random.Random,
    product: str,
    process: str,
    templates: list[FactTemplate],
    n_versions: int,
    fmt: str,
) -> list[Version]:
    n_articles = rng.randint(14, 22)
    headings = ARTICLE_HEADINGS[:n_articles]
    fact_articles = sorted(rng.sample(range(3, n_articles + 1), k=len(templates)))
    values = [rng.choice(t.values) for t in templates]
    base_paragraphs = {
        n: _paragraphs(rng, product, process, rng.randint(3, 4)) for n in range(1, n_articles + 1)
    }
    versions: list[Version] = []
    for idx, (vf, vt) in enumerate(_version_dates(rng, n_versions)):
        if idx > 0:
            # each new version changes one or two facts and one filler article
            for j in rng.sample(range(len(templates)), k=min(len(templates), rng.randint(1, 2))):
                alternatives = [v for v in templates[j].values if v != values[j]]
                if alternatives:
                    values[j] = rng.choice(alternatives)
            touched = rng.randint(1, n_articles)
            base_paragraphs[touched] = _paragraphs(rng, product, process, rng.randint(4, 5))
        facts = []
        for t, art, val in zip(templates, fact_articles, values, strict=True):
            f = render_fact(t, product, val)
            f.article = art
            facts.append(f)
        articles = []
        for n in range(1, n_articles + 1):
            paragraphs = list(base_paragraphs[n])
            for f in facts:
                if f.article == n:
                    paragraphs.insert(1, f.statement)
            articles.append(Article(number=n, heading=headings[n - 1], paragraphs=paragraphs))
        versions.append(Version(idx + 1, vf, vt, fmt, articles, facts))
    return versions


def _anchor_policies(rng: random.Random) -> list[Policy]:
    """Hand-specified documents used by the user journeys in BUILD.md §3.4."""
    anchors: list[Policy] = []

    poa_values = [
        (1, "2024-01-01", "2025-01-01", 180),
        (2, "2025-01-01", "2026-03-01", 120),
        (3, "2026-03-01", None, 90),
    ]
    kyc = Policy(
        "KYC-0042",
        "Proof of Address Requirements",
        "kyc",
        "Head of Compliance",
        "Proof of Address",
        None,
        ["all"],
    )
    for ver, vf, vt, days in poa_values:
        fact = Fact(
            "poa_max_age_days",
            4,
            days,
            "days",
            f"A proof-of-address document must not be older than {days} days at the date of onboarding.",
            "What is the maximum age of a proof-of-address document?",
            False,
        )
        articles = []
        for n, heading in enumerate(ARTICLE_HEADINGS[:12], start=1):
            paragraphs = _paragraphs(rng, "Northwind accounts", "proof of address", 3)
            if n == 4:
                heading = "Acceptable Proof of Address"
                paragraphs.insert(1, fact.statement)
            articles.append(Article(n, heading, paragraphs))
        kyc.versions.append(Version(ver, vf, vt, "pdf" if ver == 3 else "md", articles, [fact]))
    anchors.append(kyc)

    aml = Policy(
        "AML-0107",
        "Correspondent Banking Due Diligence",
        "aml",
        "MLRO",
        "Correspondent Relationships",
        None,
        ["compliance"],
    )
    for ver, vf, vt, months in [
        (1, "2023-02-01", "2024-02-01", 36),
        (2, "2024-02-01", "2025-06-01", 24),
        (3, "2025-06-01", None, 18),
    ]:
        fact = Fact(
            "correspondent_recert_months",
            5,
            months,
            "months",
            f"Correspondent banking relationships are re-certified every {months} months.",
            "How often are correspondent banking relationships re-certified?",
            False,
        )
        articles = []
        for n, heading in enumerate(ARTICLE_HEADINGS[:12], start=1):
            paragraphs = _paragraphs(rng, "correspondent accounts", "correspondent due diligence", 3)
            if n == 5:
                paragraphs.insert(1, fact.statement)
            articles.append(Article(n, heading, paragraphs))
        aml.versions.append(Version(ver, vf, vt, "docx" if ver == 3 else "md", articles, [fact]))
    anchors.append(aml)

    legal = Policy(
        "CMP-0215",
        "Litigation Hold Exceptions for Complaint Files",
        "complaints",
        "Legal Counsel",
        "Litigation Hold",
        None,
        ["legal"],
    )
    for ver, vf, vt, years in [(1, "2024-04-01", "2025-09-01", 8), (2, "2025-09-01", None, 10)]:
        fact = Fact(
            "litigation_hold_years",
            3,
            years,
            "years",
            f"Complaint files under a litigation hold are preserved for {years} years after the hold is lifted, overriding the standard deletion schedule.",
            "How long are complaint files under a litigation hold preserved after the hold is lifted?",
            False,
        )
        articles = []
        for n, heading in enumerate(ARTICLE_HEADINGS[:10], start=1):
            paragraphs = _paragraphs(rng, "complaint files", "litigation hold", 3)
            if n == 3:
                paragraphs.insert(1, fact.statement)
            articles.append(Article(n, heading, paragraphs))
        legal.versions.append(Version(ver, vf, vt, "html", articles, [fact]))
    anchors.append(legal)
    return anchors


def build_corpus(seed: int = SEED, n_policies: int = N_POLICIES) -> list[Policy]:
    rng = random.Random(seed)
    policies = _anchor_policies(rng)
    reserved_ids = {p.document_id for p in policies}
    used_pairs: set[tuple[str, str]] = set()
    used_subjects: set[tuple[str, str, str]] = set()
    counters = {prefix: 0 for prefix in DOMAINS}
    prefixes = list(DOMAINS)
    while len(policies) < n_policies:
        prefix = prefixes[len(policies) % len(prefixes)]
        domain = DOMAINS[prefix]
        process = rng.choice(PROCESSES[domain])
        product = rng.choice(PRODUCTS)
        if (domain, process, product) in used_subjects:
            continue
        free = [t for t in FACTS[domain] if (product, t.key) not in used_pairs]
        if len(free) < 2:
            continue
        templates = rng.sample(free, k=min(len(free), rng.randint(2, 3)))
        counters[prefix] += 1
        document_id = f"{prefix}-{counters[prefix] * 7 % 10000:04d}"
        while document_id in reserved_ids:
            counters[prefix] += 1
            document_id = f"{prefix}-{counters[prefix] * 7 % 10000:04d}"
        reserved_ids.add(document_id)
        used_subjects.add((domain, process, product))
        for t in templates:
            used_pairs.add((product, t.key))
        policy = Policy(
            document_id=document_id,
            title=f"{process} Policy — {product}",
            domain=domain,
            owner=rng.choice(OWNERS),
            process=process,
            product=product,
            acl_groups=list(_weighted(rng, ACL_CHOICES)),
        )
        fmt = _weighted(rng, FORMAT_CHOICES)
        policy.versions = _build_versions(rng, product, process, templates, rng.choice([2, 3, 3, 4]), fmt)
        policies.append(policy)
    policies.sort(key=lambda p: p.document_id)
    return policies


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    return asdict(policy)


def corpus_fingerprint(policies: list[Policy]) -> str:
    payload = json.dumps([policy_to_dict(p) for p in policies], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def domain_title(domain: str) -> str:
    return DOMAIN_TITLES[domain]


def tenant() -> str:
    return TENANT
