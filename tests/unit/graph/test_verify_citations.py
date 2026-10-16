"""Citation verification (FR-9, T-24)."""

from __future__ import annotations

import string

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from compliance_rag.graph.state import Citation, Claim, GeneratedAnswer
from compliance_rag.graph.verify import normalize, verify_citations
from compliance_rag.retrieval.types import Candidate, make_candidate

CID = "a" * 32
TEXT = (
    "Article 4 — Acceptable Proof of Address\n\nStaff follow the procedure.\n"
    "A proof-of-address document must not be older than 90 days at the date of onboarding.\n"
    "Transfers above EUR 15,000 require approval."
)


def ctx(text: str = TEXT, cid: str = CID, char_start: int = 1000) -> list[Candidate]:
    return [
        make_candidate(
            chunk_id=cid,
            document_id="KYC-0042",
            version=3,
            text=text,
            acl_groups=["all"],
            valid_from="2026-03-01",
            valid_to=None,
            char_start=char_start,
            char_end=char_start + len(text),
        )
    ]


def answer(*claims: Claim, text: str | None = None) -> GeneratedAnswer:
    return GeneratedAnswer(
        claims=list(claims), answer=text or " ".join(c.text for c in claims), abstained=False
    )


GOOD = Claim(
    text="Proof of address must be at most 90 days old.",
    citations=[Citation(chunk_id=CID, quote="must not be older than 90 days at the date of onboarding")],
)


def test_fabricated_quote_removed() -> None:
    fake = Claim(
        text="Proof of address may be 180 days old.",
        citations=[Citation(chunk_id=CID, quote="may be up to 180 days old for retail customers")],
    )
    result = verify_citations(answer(GOOD, fake), ctx())
    assert [c.text for c in result.claims] == [GOOD.text]
    assert result.rejected == [{"index": 1, "reason": "quote_not_found"}]
    assert not result.abstained


def test_chunk_not_in_context_rejected() -> None:
    other = Claim(
        text="Something about 90 days.",
        citations=[Citation(chunk_id="b" * 32, quote="must not be older than 90 days")],
    )
    result = verify_citations(answer(other), ctx())
    assert result.rejected == [{"index": 0, "reason": "chunk_not_in_context"}]
    assert result.abstained and result.claims == []


def test_numeric_mismatch_rejected_and_answer_rewritten() -> None:
    wrong = Claim(
        text="The limit is 30 days.",
        citations=[Citation(chunk_id=CID, quote="must not be older than 90 days at the date")],
    )
    money = Claim(
        text="Transfers above EUR 15,000 require approval.",
        citations=[Citation(chunk_id=CID, quote="Transfers above EUR 15,000 require approval.")],
    )
    result = verify_citations(answer(wrong, money, text="30 days; EUR 15,000"), ctx())
    assert result.rejected == [{"index": 0, "reason": "numeric_mismatch"}]
    assert [c.text for c in result.claims] == [money.text]
    assert result.answer == money.text  # answer carried a number (30) absent from verified claims


def test_offsets_point_into_extracted_text() -> None:
    result = verify_citations(answer(GOOD), ctx(char_start=1000))
    cit = result.claims[0].citations[0]
    local = TEXT.index("must not be older")
    assert (cit.char_start, cit.char_end) == (1000 + local, 1000 + local + len(GOOD.citations[0].quote))
    assert cit.document_id == "KYC-0042" and cit.version == 3 and cit.n == 1


def test_quote_matches_across_whitespace_and_nfkc() -> None:
    claim = Claim(
        text="Older than 90 days is not accepted.",
        citations=[Citation(chunk_id=CID, quote="must  not be\nolder than ９０ days")],
    )
    assert verify_citations(answer(claim), ctx()).claims


@settings(max_examples=80, deadline=None)
@given(st.integers(min_value=0, max_value=60), st.integers(min_value=15, max_value=60), st.data())
def test_substrings_accepted_under_whitespace_changes(start: int, length: int, data: st.DataObject) -> None:
    body = " ".join(TEXT.split())
    quote = body[start : start + length]
    assume(len(quote.strip()) >= 12 and not any(ch.isdigit() for ch in quote))
    spaced = quote.replace(" ", data.draw(st.sampled_from([" ", "  ", "\n", " \t"])))
    claim = Claim(text="A claim without numbers.", citations=[Citation(chunk_id=CID, quote=spaced.strip())])
    assert verify_citations(answer(claim), ctx()).claims


@settings(max_examples=80, deadline=None)
@given(
    st.integers(min_value=0, max_value=40),
    st.integers(min_value=0, max_value=20),
    st.sampled_from(string.ascii_letters),
)
def test_single_character_mutations_rejected(start: int, pos: int, letter: str) -> None:
    body = " ".join(TEXT.split())
    quote = body[start : start + 40]
    assume(len(quote) == 40 and quote[pos] != letter and not quote[pos].isspace())
    mutated = quote[:pos] + letter + quote[pos + 1 :]
    assume(normalize(mutated) not in normalize(TEXT))
    claim = Claim(text="A claim without numbers.", citations=[Citation(chunk_id=CID, quote=mutated)])
    assert verify_citations(answer(claim), ctx()).rejected[0]["reason"] == "quote_not_found"
