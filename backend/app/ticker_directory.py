from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Exchange


@dataclass(frozen=True)
class TickerDirectoryEntry:
    ticker: str
    company_name: str
    sector: str
    exchange: Exchange
    bse_id: str | None


@dataclass(frozen=True)
class TickerDirectoryMetadata:
    source: str = "bundled-indian-equity-directory"
    description: str = "Deterministic bundled directory for Indian equity autocomplete"
    refresh_policy: str = "manual bundle update"


DIRECTORY_METADATA = TickerDirectoryMetadata()

# This intentionally stays in-process and deterministic. It is autocomplete data,
# not a per-keystroke market-data integration.
TICKER_DIRECTORY: tuple[TickerDirectoryEntry, ...] = (
    TickerDirectoryEntry("HDFCBANK", "HDFC Bank", "Private bank", Exchange.NSE, "500180"),
    TickerDirectoryEntry("HDFCBANK", "HDFC Bank", "Private bank", Exchange.BSE, "500180"),
    TickerDirectoryEntry("INFY", "Infosys", "IT services", Exchange.NSE, "500209"),
    TickerDirectoryEntry("INFY", "Infosys", "IT services", Exchange.BSE, "500209"),
    TickerDirectoryEntry("ITC", "ITC", "Consumer staples", Exchange.NSE, "500875"),
    TickerDirectoryEntry("ITC", "ITC", "Consumer staples", Exchange.BSE, "500875"),
    TickerDirectoryEntry("PEIL", "PEIL", "Indian equity", Exchange.NSE, None),
    TickerDirectoryEntry("PEIL", "PEIL", "Indian equity", Exchange.BSE, None),
    TickerDirectoryEntry("RELIANCE", "Reliance Industries", "Diversified", Exchange.NSE, "500325"),
    TickerDirectoryEntry("RELIANCE", "Reliance Industries", "Diversified", Exchange.BSE, "500325"),
    TickerDirectoryEntry("SBIN", "State Bank of India", "Public bank", Exchange.NSE, "500112"),
    TickerDirectoryEntry("SBIN", "State Bank of India", "Public bank", Exchange.BSE, "500112"),
    TickerDirectoryEntry("TCS", "Tata Consultancy Services", "IT services", Exchange.NSE, "532540"),
    TickerDirectoryEntry("TCS", "Tata Consultancy Services", "IT services", Exchange.BSE, "532540"),
)


def search_ticker_directory(
    query: str, exchange: Exchange | None = None
) -> tuple[TickerDirectoryEntry, ...]:
    normalized = query.strip().casefold()
    matches = (
        entry
        for entry in TICKER_DIRECTORY
        if (exchange is None or entry.exchange is exchange)
        and (
            normalized in entry.ticker.casefold()
            or normalized in entry.company_name.casefold()
        )
    )
    return tuple(
        sorted(
            matches,
            key=lambda entry: (entry.ticker, 0 if entry.exchange is Exchange.NSE else 1),
        )
    )
