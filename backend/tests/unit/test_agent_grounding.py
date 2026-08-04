from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import Citation, DocumentKind, SourceDocument
from app.grounding import GroundingGuard


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

    assert result["result"].answer == GroundingGuard.FALLBACK
    assert result["result"].grounded is True
