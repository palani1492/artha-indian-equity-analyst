from datetime import UTC, datetime

from app.domain.models import DocumentKind, SourceDocument
from app.tagging import ResilientArticleTagger


async def test_lexical_article_tagger_extracts_data_driven_memory_without_llm() -> None:
    document = SourceDocument.create(
        ticker="RELIANCE",
        kind=DocumentKind.NEWS,
        title="RELIANCE profit growth beats estimates",
        url="https://example.test/reliance-results",
        content="RELIANCE wins on earnings growth but management also discusses debt.",
        published_at=datetime.now(UTC),
    )
    tags = await ResilientArticleTagger().tag(document)
    assert "RELIANCE" in tags.mentioned_tickers
    assert tags.sentiment > 0
    assert tags.impact in {"medium", "high"}
    assert tags.event_tag in {"earnings", "balance-sheet"}
