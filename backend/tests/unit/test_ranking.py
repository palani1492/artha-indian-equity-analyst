from __future__ import annotations

from decimal import Decimal

from app.domain.models import Exchange, InvestorPersona, RiskTolerance, Stock
from app.ranking import StockRanker


def stock(
    ticker: str, debt: str, dividend: str, sentiment: float, growth: str
) -> Stock:
    return Stock(
        ticker=ticker,
        exchange=Exchange.NSE,
        name=ticker,
        price_inr=Decimal(100),
        debt_to_equity=Decimal(debt),
        dividend_yield=Decimal(dividend),
        revenue_growth=Decimal(growth),
        roe=Decimal(18),
        sentiment=sentiment,
        sector="IT",
    )


def test_ranker_hard_filters_high_debt_and_is_deterministic() -> None:
    persona = InvestorPersona(
        user_id="u1",
        risk_tolerance=RiskTolerance.CONSERVATIVE,
        dividend_focused=True,
        avoid_high_debt=True,
        max_debt_to_equity=Decimal(1),
    )
    candidates = [
        stock("HIGHDEBT", "2.5", "5", 0.9, "20"),
        stock("SAFE", "0.1", "4", 0.4, "8"),
        stock("GROWTH", "0.6", "1", 0.8, "25"),
    ]
    ranker = StockRanker()

    first = ranker.rank(persona, candidates)
    second = ranker.rank(persona, list(reversed(candidates)))

    assert [item.stock.ticker for item in first] == [
        item.stock.ticker for item in second
    ]
    assert "HIGHDEBT" not in [item.stock.ticker for item in first]
    assert first[0].stock.ticker == "SAFE"
    assert first[0].reasons
