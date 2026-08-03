from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.container import build_container
from app.domain.models import (
    DocumentKind,
    Exchange,
    SourceDocument,
    Stock,
    normalize_ticker,
)
from app.settings import Settings
from pydantic import ValidationError


def test_ticker_normalization_accepts_nse_suffix() -> None:
    assert normalize_ticker(" reliance.ns ") == ("RELIANCE", Exchange.NSE)
    assert normalize_ticker("500325.bo") == ("500325", Exchange.BSE)


@pytest.mark.parametrize("ticker", ["", "../../etc", "RELIANCE;DROP", "A" * 21])
def test_ticker_normalization_rejects_untrusted_input(ticker: str) -> None:
    with pytest.raises(ValueError):
        normalize_ticker(ticker)


def test_stock_requires_nonnegative_inr_price() -> None:
    with pytest.raises(ValidationError):
        Stock(ticker="TCS", exchange=Exchange.NSE, name="TCS", price_inr=-1)


def test_database_url_is_composed_from_aws_parts() -> None:
    settings = Settings(
        database_url=None,
        db_host="db.internal",
        db_port=5432,
        db_name="sentellent",
        db_username="api-user",
        db_password="p@ss word",
    )
    assert settings.resolved_database_url == (
        "postgresql+asyncpg://api-user:p%40ss+word@db.internal:5432/sentellent"
    )


def test_explicit_database_url_takes_precedence() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///./test.db", db_host="ignored")
    assert settings.resolved_database_url == "sqlite+aiosqlite:///./test.db"


def test_syndicated_article_content_is_deduplicated_across_tracking_urls() -> None:
    values = {
        "ticker": "TCS",
        "kind": DocumentKind.NEWS,
        "title": "TCS update",
        "content": "TCS wins a major Indian technology order.",
        "published_at": datetime.now(UTC),
    }
    first = SourceDocument.create(url="https://source-a.test/story", **values)
    second = SourceDocument.create(url="https://source-b.test/syndicated", **values)
    assert first.content_hash == second.content_hash


def test_csv_environment_lists_are_parsed_without_json(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.test,https://b.test")
    monkeypatch.setenv("RSS_FEEDS", "https://feed-a.test/rss,https://feed-b.test/rss")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ("https://a.test", "https://b.test")
    assert settings.rss_feeds == ("https://feed-a.test/rss", "https://feed-b.test/rss")


def test_blank_optional_session_secret_is_treated_as_unconfigured() -> None:
    assert Settings(session_secret="").session_secret is None


def test_production_refuses_ephemeral_in_memory_persistence() -> None:
    with pytest.raises(ValueError, match="Persistent DATABASE_URL"):
        build_container(Settings(app_env="production", database_url=None, db_host=None))
