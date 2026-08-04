from datetime import UTC
from decimal import Decimal

from app.domain.models import Exchange, SourceTier, Stock
from app.providers import LiveIndianMarketDataProvider


def test_live_provider_canonicalizes_tracking_urls_for_deduplication() -> None:
    url = "HTTPS://News.Example.com/story/?utm_source=rss&b=2&a=1#section"
    assert (
        LiveIndianMarketDataProvider.canonicalize_url(url)
        == "https://news.example.com/story?a=1&b=2"
    )


def _stock() -> Stock:
    return Stock(
        ticker="TCS",
        exchange=Exchange.NSE,
        name="Tata Consultancy Services",
        sector="IT",
        price_inr=Decimal("4125.50"),
        market_cap_crore=Decimal(1500000),
        pe_ratio=Decimal("32.4"),
        debt_to_equity=Decimal("0.1"),
        dividend_yield=Decimal("1.45"),
        roe=Decimal("48.3"),
        revenue_growth=Decimal("9.1"),
    )


def test_live_provider_parses_only_relevant_rss_items_and_tags_sentiment() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    payload = b"""<rss><channel>
      <item><title>TCS profit growth beats estimates</title>
        <description><![CDATA[<p>Tata Consultancy Services wins a large order.</p>]]></description>
        <link>https://news.example.test/tcs?utm_source=rss</link>
        <pubDate>Fri, 01 Aug 2026 09:00:00 +0000</pubDate></item>
      <item><title>Unrelated market story</title><description>No matching company.</description>
        <link>https://news.example.test/other</link></item>
    </channel></rss>"""
    documents = provider._parse_feed(payload, _stock())
    assert len(documents) == 1
    assert str(documents[0].url) == "https://news.example.test/tcs"
    assert documents[0].sentiment > 0
    assert documents[0].published_at.tzinfo is UTC
    assert documents[0].source_tier is SourceTier.SECONDARY


def test_sebi_feed_entries_are_primary() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    payload = b"""<rss><channel>
      <item><title>TCS disclosure</title><description>Tata Consultancy Services filing.</description>
        <link>https://www.sebi.gov.in/tcs-disclosure</link>
        <pubDate>Fri, 01 Aug 2026 09:00:00 +0000</pubDate></item>
    </channel></rss>"""

    documents = provider._parse_feed(payload, _stock(), source_tier=SourceTier.PRIMARY)

    assert documents[0].source_tier is SourceTier.PRIMARY


def test_live_provider_matches_company_aliases_in_rss_items() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    stock = _stock().model_copy(
        update={"ticker": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited"}
    )
    payload = b"""<rss><channel>
      <item><title>Dr Reddy's Laboratories profit growth beats estimates</title>
        <description>Dr Reddy's wins a large order.</description>
        <link>https://news.example.test/drreddy</link>
        <pubDate>Fri, 01 Aug 2026 09:00:00 +0000</pubDate></item>
    </channel></rss>"""
    documents = provider._parse_feed(payload, stock)
    assert len(documents) == 1


def test_live_provider_does_not_match_single_letter_m_aliases() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    stock = _stock().model_copy(
        update={"ticker": "M&M", "name": "Mahindra & Mahindra Limited"}
    )
    payload = b"""<rss><channel>
      <item><title>Bharti Airtel Q1 Results: Net profit surges</title>
        <description>ARPU rises as telecom demand improves.</description>
        <link>https://news.example.test/airtel</link>
        <pubDate>Fri, 01 Aug 2026 09:00:00 +0000</pubDate></item>
    </channel></rss>"""

    assert provider._parse_feed(payload, stock) == ()


def test_live_fundamentals_document_contains_groundable_inr_values() -> None:
    document = LiveIndianMarketDataProvider._fundamentals_document(_stock())
    assert "INR 4125.50" in document.content
    assert "Debt-to-equity is 0.1" in document.content
    assert document.event_tag == "live-fundamentals"
    assert document.source_tier is SourceTier.SECONDARY
    assert (
        document.id == LiveIndianMarketDataProvider._fundamentals_document(_stock()).id
    )


def test_live_provider_helpers_are_safe_for_missing_upstream_values() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    assert provider._clean_html("<b> hello </b> world") == "hello world"
    assert provider._published_at("not-a-date").tzinfo is UTC
    assert provider._decimal(None) is None


def test_live_provider_normalizes_fractional_and_percent_values() -> None:
    assert LiveIndianMarketDataProvider._percentage("0.0174") == Decimal("1.74")
    assert LiveIndianMarketDataProvider._percentage("1.74") == Decimal("1.74")


def test_rss_documents_use_stable_url_identity_for_syndicated_duplicates() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    payload = b"""<rss><channel>
      <item><title>TCS profit growth</title><description>First feed copy</description>
        <link>https://news.example.test/story?utm_source=one</link>
        <pubDate>Fri, 01 Aug 2026 09:00:00 +0000</pubDate></item>
      <item><title>TCS profit growth</title><description>Second feed copy</description>
        <link>https://news.example.test/story?utm_medium=two</link>
        <pubDate>Fri, 01 Aug 2026 10:00:00 +0000</pubDate></item>
    </channel></rss>"""
    documents = provider._parse_feed(payload, _stock())
    assert len(documents) == 2
    assert documents[0].content_hash == documents[1].content_hash


async def test_live_provider_skips_an_unavailable_feed() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())

    async def unavailable(url: str, stock: Stock):
        raise TimeoutError

    provider._fetch_feed = unavailable
    assert await provider._safe_fetch_feed("https://feed.test/rss", _stock()) == ()


def test_live_provider_parses_namespaced_atom_entries() -> None:
    provider = LiveIndianMarketDataProvider(rss_feeds=())
    payload = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Tata Consultancy Services wins a major order</title>
        <link href="https://news.example.test/tcs-atom" />
        <updated>2026-08-01T09:00:00Z</updated>
        <summary><![CDATA[<p>TCS profit growth beats estimates.</p>]]></summary>
      </entry>
    </feed>"""

    documents = provider._parse_feed(payload, _stock())

    assert len(documents) == 1
    assert str(documents[0].url) == "https://news.example.test/tcs-atom"
    assert documents[0].published_at.isoformat() == "2026-08-01T09:00:00+00:00"
