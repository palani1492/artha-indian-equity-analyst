from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import Citation, DocumentKind, SourceDocument
from app.grounding import GroundingGuard


def source() -> SourceDocument:
    return SourceDocument.create(
        ticker="TCS",
        kind=DocumentKind.FUNDAMENTALS,
        title="TCS fundamentals",
        url="https://example.test/tcs",
        content="TCS price is INR 4,125.50 and debt-to-equity is 0.10.",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_numeric_claim_requires_a_valid_citation_and_source_support() -> None:
    doc = source()
    citation = Citation(index=1, document_id=doc.id, title=doc.title, url=doc.url)
    guard = GroundingGuard()

    result = guard.validate(
        "TCS trades at INR 4,125.50 [1].",
        (citation,),
        (doc,),
    )
    assert result.is_grounded is True

    missing_citation = guard.validate("TCS trades at INR 4,125.50.", (), (doc,))
    assert missing_citation.is_grounded is False

    hallucinated = guard.validate("TCS trades at INR 9,999 [1].", (citation,), (doc,))
    assert hallucinated.is_grounded is False


def test_guard_rejects_non_inr_currency_and_unknown_citations() -> None:
    doc = source()
    guard = GroundingGuard()
    assert guard.validate("It costs $50 [1].", (), (doc,)).is_grounded is False
    assert guard.validate("Price is INR 4,125.50 [7].", (), (doc,)).is_grounded is False


def test_guard_accepts_indian_currency_notation_when_sourced() -> None:
    doc = source()
    citation = Citation(index=1, document_id=doc.id, title=doc.title, url=doc.url)
    guard = GroundingGuard()
    assert guard.validate(
        "TCS trades at Rs. 4,125.50 [1].", (citation,), (doc,)
    ).is_grounded
    assert guard.validate(
        "TCS trades at ₹4,125.50 [1].", (citation,), (doc,)
    ).is_grounded


def test_guard_returns_safe_fallback_for_unsupported_answer() -> None:
    result = GroundingGuard().enforce("Revenue is INR 999 crore.", (), ())
    assert result.answer == "I don't have that in the ingested data."
    assert result.citations == ()


def test_guard_rejects_uncited_non_numeric_factual_claim() -> None:
    assert (
        GroundingGuard()
        .validate("TCS outlook is positive.", (), (source(),))
        .is_grounded
        is False
    )


def test_guard_rejects_qualitative_claim_not_present_in_cited_source() -> None:
    doc = source()
    citation = Citation(index=1, document_id=doc.id, title=doc.title, url=doc.url)
    result = GroundingGuard().validate(
        "Management quality improved materially [1].", (citation,), (doc,)
    )
    assert result.is_grounded is False


def test_guard_rejects_unsupported_qualitative_claim_beside_a_sourced_number() -> (
    None
):
    doc = source()
    citation = Citation(index=1, document_id=doc.id, title=doc.title, url=doc.url)
    result = GroundingGuard().validate(
        "TCS trades at INR 4,125.50 and management quality improved materially [1].",
        (citation,),
        (doc,),
    )
    assert result.is_grounded is False
