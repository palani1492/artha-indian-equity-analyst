from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import Citation, DocumentKind, SourceDocument


@pytest.mark.asyncio
async def test_invalid_authoritative_draft_cannot_be_marked_grounded(container) -> None:
    source = SourceDocument.create(
        ticker="TCS",
        kind=DocumentKind.FUNDAMENTALS,
        title="TCS fundamentals",
        url="https://example.test/tcs",
        content="TCS price is INR 4,125.50.",
        published_at=datetime.now(UTC),
    )
    citation = Citation(index=1, document_id=source.id, title=source.title, url=source.url)
    state = {
        "user_id": "grounding@example.com",
        "answer_kind": "research",
        "draft": "TCS trades at INR 4,125.50 and management quality improved materially [1].",
        "authoritative_draft": "TCS trades at INR 4,125.50 and management quality improved materially [1].",
        "citations": (citation,),
        "sources": (source,),
        "persona_updated": False,
        "recommendations": (),
    }

    result = await container.agent._guard_node(state)

    assert result["result"].grounded is True
    assert result["result"].citations
    assert "management quality" not in result["result"].answer
    assert result["result"].grounded is True


@pytest.mark.asyncio
async def test_evidence_inventory_is_grounded(container) -> None:
    source = SourceDocument.create(
        ticker="TCS",
        kind=DocumentKind.FUNDAMENTALS,
        title="TCS fundamentals",
        url="https://example.test/tcs",
        content="TCS price is INR 4,125.50. P/E ratio is 14.2.",
        published_at=datetime.now(UTC),
    )

    draft, citations = container.agent._evidence_inventory_draft((source,))
    result = container.agent._guard.validate(draft, citations, (source,))

    assert result.is_grounded is True
    assert citations
