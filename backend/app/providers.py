from __future__ import annotations

import asyncio
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import ClassVar, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.domain.models import (
    DocumentKind,
    Exchange,
    SourceDocument,
    SourceTier,
    Stock,
    normalize_ticker,
)

TAG_PATTERN = re.compile(r"<[^>]+>")
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
}


class MarketDataProvider(Protocol):
    async def fetch(self, ticker: str) -> tuple[Stock, tuple[SourceDocument, ...]]: ...


class DemoMarketDataProvider:
    """Stable, explicit fixtures; useful for reviewers when upstream sites rate-limit."""

    _STOCKS: ClassVar[dict[str, tuple]] = {
        "TCS": (
            "Tata Consultancy Services",
            "IT",
            "4125.50",
            "14.2",
            "32.4",
            "0.10",
            "1.45",
            "48.3",
            "9.1",
            0.65,
            "532540",
        ),
        "INFY": (
            "Infosys",
            "IT",
            "1842.30",
            "7.6",
            "28.2",
            "0.09",
            "2.10",
            "31.7",
            "8.4",
            0.55,
            "500209",
        ),
        "RELIANCE": (
            "Reliance Industries",
            "Energy",
            "2976.80",
            "20.1",
            "27.5",
            "1.18",
            "0.35",
            "9.4",
            "11.7",
            -0.25,
            "500325",
        ),
        "HDFCBANK": (
            "HDFC Bank",
            "Banking",
            "1712.45",
            "12.8",
            "19.8",
            "0.95",
            "1.12",
            "16.2",
            "14.3",
            0.35,
            "500180",
        ),
        "ITC": (
            "ITC",
            "FMCG",
            "493.20",
            "6.2",
            "29.1",
            "0.01",
            "3.55",
            "28.4",
            "7.2",
            0.50,
            "500875",
        ),
    }

    async def fetch(self, ticker: str) -> tuple[Stock, tuple[SourceDocument, ...]]:
        symbol, exchange = normalize_ticker(ticker)
        data = self._STOCKS.get(symbol)
        if data is None:
            raise LookupError(f"No demo data is available for {symbol}")
        (
            name,
            sector,
            price,
            market_cap_lakh_crore,
            pe,
            debt,
            dividend,
            roe,
            growth,
            sentiment,
            bse_id,
        ) = data
        stock = Stock(
            ticker=symbol,
            exchange=exchange,
            bse_id=bse_id,
            name=name,
            sector=sector,
            price_inr=Decimal(price),
            market_cap_crore=Decimal(market_cap_lakh_crore) * Decimal(100000),
            pe_ratio=Decimal(pe),
            debt_to_equity=Decimal(debt),
            dividend_yield=Decimal(dividend),
            roe=Decimal(roe),
            revenue_growth=Decimal(growth),
            sentiment=sentiment,
            change_pct=0.0,
        )
        now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        fundamentals = SourceDocument.create(
            ticker=symbol,
            kind=DocumentKind.FUNDAMENTALS,
            title=f"{name} fundamentals snapshot",
            url=f"https://www.screener.in/company/{symbol}/consolidated/",
            content=(
                f"{name} ({symbol}, {exchange}) price is INR {price}. "
                f"Market capitalisation is INR {stock.market_cap_crore} crore. "
                f"P/E ratio is {pe}. Debt-to-equity is {debt}. Dividend yield is {dividend}%. "
                f"Return on equity is {roe}% and revenue growth is {growth}%."
            ),
            published_at=now,
            event_tag="fundamentals",
        )
        direction = (
            "positive"
            if sentiment > 0.15
            else "negative"
            if sentiment < -0.15
            else "neutral"
        )
        news = SourceDocument.create(
            ticker=symbol,
            kind=DocumentKind.NEWS,
            title=f"{name}: weekly Indian market update",
            url=f"https://example.com/indian-markets/{symbol.lower()}-weekly-update",
            content=(
                f"Recent reporting on {name} is {direction}. Analysts highlighted the company's "
                f"{sector.lower()} outlook and balance-sheet trend for Indian investors."
            ),
            published_at=now - timedelta(days=1),
            sentiment=sentiment,
            impact="high" if abs(sentiment) >= 0.5 else "medium",
            event_tag="weekly-update",
        )
        return stock, (fundamentals, news)


class LiveIndianMarketDataProvider:
    """Live yfinance fundamentals plus configurable Indian-market RSS feeds."""

    def __init__(
        self,
        *,
        rss_feeds: tuple[str, ...],
        request_timeout_seconds: float = 10.0,
        min_request_interval_seconds: float = 1.0,
        max_items_per_feed: int = 100,
        user_agent: str = "SentellentResearchBot/1.0 (+research demo; respectful RSS polling)",
    ) -> None:
        self._rss_feeds = rss_feeds
        self._timeout = request_timeout_seconds
        self._minimum_interval = min_request_interval_seconds
        self._max_items_per_feed = max_items_per_feed
        self._user_agent = user_agent
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def fetch(self, ticker: str) -> tuple[Stock, tuple[SourceDocument, ...]]:
        symbol, exchange = normalize_ticker(ticker)
        stock = await asyncio.to_thread(self._fetch_yfinance, symbol, exchange)
        documents = [self._fundamentals_document(stock)]
        feed_documents = await asyncio.gather(
            *(self._safe_fetch_feed(url, stock) for url in self._rss_feeds)
        )
        documents.extend(document for feed in feed_documents for document in feed)
        return stock, tuple(documents)

    @staticmethod
    def canonicalize_url(url: str) -> str:
        parts = urlsplit(url.strip())
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parts.query)
                if key.lower() not in TRACKING_QUERY_KEYS
            )
        )
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                query,
                "",
            )
        )

    def _fetch_yfinance(self, symbol: str, exchange: Exchange) -> Stock:
        try:
            import yfinance as yf  # type: ignore[import-untyped]
        except ImportError as error:
            raise RuntimeError("Live mode requires the yfinance package") from error
        suffix = ".NS" if exchange is Exchange.NSE else ".BO"
        info = yf.Ticker(f"{symbol}{suffix}").get_info()
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            raise LookupError(f"No live INR quote available for {symbol}")
        market_cap = info.get("marketCap")
        debt_to_equity = self._decimal(info.get("debtToEquity"))
        dividend_yield = self._percentage(info.get("dividendYield"))
        roe = self._percentage(info.get("returnOnEquity"))
        revenue_growth = self._percentage(info.get("revenueGrowth"))
        change_pct = self._decimal(
            info.get("regularMarketChangePercent")
            or info.get("regularMarketChangePercentRaw")
            or info.get("changePercent")
        )
        return Stock(
            ticker=symbol,
            exchange=exchange,
            name=str(info.get("longName") or info.get("shortName") or symbol),
            sector=str(info.get("sector") or "Other"),
            price_inr=Decimal(str(price)),
            market_cap_crore=Decimal(str(market_cap)) / Decimal(10000000)
            if market_cap
            else None,
            pe_ratio=self._decimal(info.get("trailingPE")),
            debt_to_equity=debt_to_equity / Decimal(100)
            if debt_to_equity is not None
            else None,
            dividend_yield=dividend_yield,
            roe=roe,
            revenue_growth=revenue_growth,
            change_pct=float(change_pct or 0),
        )

    async def _fetch_feed(self, url: str, stock: Stock) -> tuple[SourceDocument, ...]:
        await self._respect_rate_limit()
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            response = await client.get(url, headers={"User-Agent": self._user_agent})
            response.raise_for_status()
        return self._parse_feed(
            response.content, stock, source_tier=self._feed_source_tier(url)
        )

    async def _safe_fetch_feed(
        self, url: str, stock: Stock
    ) -> tuple[SourceDocument, ...]:
        try:
            return await self._fetch_feed(url, stock)
        except (httpx.HTTPError, ET.ParseError, TimeoutError, ValueError):
            return ()

    async def _respect_rate_limit(self) -> None:
        async with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._minimum_interval:
                await asyncio.sleep(self._minimum_interval - elapsed)
            self._last_request_at = time.monotonic()

    def _parse_feed(
        self,
        payload: bytes,
        stock: Stock,
        source_tier: SourceTier = SourceTier.SECONDARY,
    ) -> tuple[SourceDocument, ...]:
        root = ET.fromstring(payload)
        matches: list[SourceDocument] = []
        aliases = self._company_aliases(stock)
        entries = [
            element
            for element in root.iter()
            if self._local_name(element.tag) in {"item", "entry"}
        ][: self._max_items_per_feed]
        for item in entries:
            title = self._element_text(item, {"title"})
            description = self._clean_html(
                self._element_text(
                    item, {"description", "summary", "content", "encoded"}
                )
            )
            combined = " ".join(part for part in (title, description) if part).strip()
            if not combined:
                continue
            normalized_combined = self._normalize_company_text(combined)
            if not any(alias in normalized_combined for alias in aliases):
                continue
            raw_url = self._entry_url(item)
            if not raw_url.startswith(("http://", "https://")):
                continue
            published_at = self._published_at(
                self._element_text(item, {"pubDate", "published", "updated", "date"})
            )
            matches.append(
                SourceDocument.create(
                    ticker=stock.ticker,
                    kind=DocumentKind.NEWS,
                    title=title or f"{stock.ticker} market update",
                    url=self.canonicalize_url(raw_url),
                    content=combined,
                    published_at=published_at,
                    source_tier=source_tier,
                    sentiment=self._sentiment(combined),
                    impact="medium",
                    event_tag="rss-news",
                    dedupe_key=self.canonicalize_url(raw_url),
                )
            )
        return tuple(matches)

    @staticmethod
    def _feed_source_tier(url: str) -> SourceTier:
        hostname = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
        return (
            SourceTier.PRIMARY
            if hostname == "sebi.gov.in" or hostname.endswith(".sebi.gov.in")
            else SourceTier.SECONDARY
        )

    @classmethod
    def _company_aliases(cls, stock: Stock) -> tuple[str, ...]:
        normalized_name = cls._normalize_company_text(stock.name)
        shortened_name = normalized_name
        for suffix in (" limited", " ltd", " plc"):
            shortened_name = shortened_name.removesuffix(suffix)
        words = shortened_name.split()
        aliases = {
            cls._normalize_company_text(stock.ticker),
            shortened_name,
            " ".join(words[:2]) if len(words) >= 2 else shortened_name,
        }
        return tuple(
            sorted(
                (alias for alias in aliases if len(alias) >= 3),
                key=len,
                reverse=True,
            )
        )

    @staticmethod
    def _normalize_company_text(value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())

    @staticmethod
    def _fundamentals_document(stock: Stock) -> SourceDocument:
        fields = [
            f"{stock.name} ({stock.ticker}, {stock.exchange}) price is INR {stock.price_inr}."
        ]
        for label, value, suffix in (
            ("Market capitalisation", stock.market_cap_crore, " crore"),
            ("P/E ratio", stock.pe_ratio, ""),
            ("Debt-to-equity", stock.debt_to_equity, ""),
            ("Dividend yield", stock.dividend_yield, "%"),
            ("Return on equity", stock.roe, "%"),
            ("Revenue growth", stock.revenue_growth, "%"),
        ):
            if value is not None:
                fields.append(f"{label} is {value}{suffix}.")
        exchange_suffix = "NS" if stock.exchange is Exchange.NSE else "BO"
        return SourceDocument.create(
            ticker=stock.ticker,
            kind=DocumentKind.FUNDAMENTALS,
            title=f"{stock.name} live fundamentals",
            url=f"https://finance.yahoo.com/quote/{stock.ticker}.{exchange_suffix}/",
            content=" ".join(fields),
            published_at=datetime.now(UTC),
            event_tag="live-fundamentals",
            dedupe_key=f"{stock.ticker}:fundamentals",
            source_tier=SourceTier.SECONDARY,
        )

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    @classmethod
    def _element_text(cls, item: ET.Element, names: set[str]) -> str:
        wanted = {name.lower() for name in names}
        for element in item.iter():
            if cls._local_name(element.tag) not in wanted:
                continue
            value = "".join(element.itertext()).strip()
            if value:
                return html.unescape(value)
        return ""

    @classmethod
    def _entry_url(cls, item: ET.Element) -> str:
        for element in item.iter():
            if cls._local_name(element.tag) != "link":
                continue
            href = element.attrib.get("href", "").strip()
            value = href or "".join(element.itertext()).strip()
            if value.startswith(("http://", "https://")):
                return value
        return ""

    @staticmethod
    def _clean_html(value: str) -> str:
        return " ".join(TAG_PATTERN.sub(" ", value).split())

    @staticmethod
    def _published_at(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return datetime.now(UTC)
        try:
            return (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
        except (TypeError, ValueError):
            return datetime.now(UTC)

    @staticmethod
    def _sentiment(text: str) -> float:
        normalized = text.lower()
        positives = sum(
            word in normalized
            for word in ("profit", "growth", "beats", "upgrade", "wins")
        )
        negatives = sum(
            word in normalized
            for word in ("loss", "debt", "downgrade", "falls", "probe")
        )
        return max(-1.0, min(1.0, (positives - negatives) / 3))

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @classmethod
    def _percentage(cls, value: object) -> Decimal | None:
        decimal = cls._decimal(value)
        if decimal is None:
            return None
        return decimal * Decimal(100) if abs(decimal) <= Decimal(1) else decimal
