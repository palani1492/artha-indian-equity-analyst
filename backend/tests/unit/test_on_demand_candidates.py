from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.models import Exchange, IngestionResult, Stock
from app.ticker_directory import TickerDirectoryEntry


class RecordingIngestion:
    def __init__(self, repository, failing: set[str] = ()) -> None:
        self.repository = repository
        self.failing = failing
        self.calls: list[str] = []

    async def ingest(self, ticker: str) -> IngestionResult:
        self.calls.append(ticker)
        if ticker in self.failing:
            raise LookupError(f"No provider data for {ticker}")
        stock = Stock(
            ticker=ticker,
            name=ticker,
            sector="IT",
            price_inr=Decimal(100),
        )
        await self.repository.upsert_stock(stock)
        return IngestionResult(ticker=ticker, inserted=1, skipped=0, sentiment=0)


def directory_entry(ticker: str) -> TickerDirectoryEntry:
    return TickerDirectoryEntry(
        ticker=ticker,
        company_name=ticker,
        sector="IT services",
        exchange=Exchange.NSE,
        bse_id=None,
    )


async def prepare_followed_tcs(container) -> None:
    await container.ingestion.ingest("TCS")
    await container.repository.follow_stock("candidate-user", "TCS")


async def test_on_demand_candidates_are_ranked_without_follow_side_effect(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    await prepare_followed_tcs(container)
    ingestion = RecordingIngestion(container.repository)
    container.agent._ingestion = ingestion

    result = await container.agent.chat(
        "candidate-user",
        "find 2 to 3 technology stocks within INR 10000 that match my investor profile",
    )

    assert ingestion.calls == ["HCLTECH"]
    assert result.metadata["on_demand_indexed_tickers"] == ["HCLTECH"]
    assert result.metadata["universe"] == "followed + on-demand directory"
    assert {item.stock.ticker for item in result.recommendations} >= {"TCS", "HCLTECH"}
    assert await container.repository.list_followed_tickers("candidate-user") == ("TCS",)


async def test_on_demand_failure_isolated_and_reported(container) -> None:
    await prepare_followed_tcs(container)
    ingestion = RecordingIngestion(container.repository, failing={"HCLTECH"})
    container.agent._ingestion = ingestion

    result = await container.agent.chat(
        "candidate-user",
        "find 2 to 3 technology stocks within INR 10000 that match my investor profile",
    )

    assert ingestion.calls == ["HCLTECH", "INFY"]
    assert result.metadata["on_demand_indexed_tickers"] == ["INFY"]
    assert result.metadata["on_demand_failed_tickers"] == ["HCLTECH"]
    assert "HCLTECH" in result.metadata["on_demand_limitation"]
    assert {item.stock.ticker for item in result.recommendations} >= {"TCS", "INFY"}


async def test_on_demand_candidate_selection_is_capped_at_eight(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = tuple(directory_entry(f"CANDIDATE{i}") for i in range(10))
    monkeypatch.setattr("app.agent.TICKER_DIRECTORY", entries)
    ingestion = RecordingIngestion(container.repository, failing={entry.ticker for entry in entries})
    container.agent._ingestion = ingestion

    result = await container.agent.chat(
        "candidate-user",
        "find 9 to 10 technology stocks that match my investor profile",
    )

    assert len(ingestion.calls) == 8
    assert len(result.metadata["on_demand_failed_tickers"]) == 8


async def test_list_all_stocks_returns_indexed_stocks_in_ticker_order(container) -> None:
    await container.repository.upsert_stock(
        Stock(ticker="ZOMATO", name="Zomato", price_inr=Decimal(100))
    )
    await container.repository.upsert_stock(
        Stock(ticker="INFY", name="Infosys", price_inr=Decimal(100))
    )

    stocks = await container.repository.list_all_stocks()

    assert tuple(stock.ticker for stock in stocks) == ("INFY", "ZOMATO")
