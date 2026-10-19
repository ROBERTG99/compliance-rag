"""PII redaction before provider calls (T-23)."""

from compliance_rag.guard.pii import redact


def test_redacts_email_phone_and_accounts() -> None:
    text = (
        "Contact jane.doe@example.com or +44 20 7946 0958 about IBAN DE89 3704 0044 0532 0130 00 "
        "and card 4111 1111 1111 1111."
    )
    out = redact(text)
    assert "jane.doe@example.com" not in out and "[EMAIL]" in out
    assert "7946" not in out and "[PHONE]" in out
    assert "DE89" not in out and "4111" not in out and "[ACCOUNT]" in out


def test_keeps_policy_numbers_and_dates() -> None:
    text = "Transfers above EUR 250,000 on 2026-03-01 within 30 days at 99 percent; KYC-0042 v3."
    assert redact(text) == text
