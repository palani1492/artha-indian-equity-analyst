from __future__ import annotations

from decimal import Decimal

from app.complex_questions import (
    allocate_budget,
    filter_candidates,
    parse_complex_question,
)
from app.domain.models import Stock


def stock(ticker: str, price: str, sector: str = "IT") -> Stock:
    return Stock(ticker=ticker, name=ticker, sector=sector, price_inr=Decimal(price))


def test_parser_extracts_count_budget_sector_and_profile_intent() -> None:
    constraints = parse_complex_question(
        "find me 1 to 5 technology stocks within INR 20000 that match my investor profile"
    )

    assert constraints is not None
    assert constraints.min_count == 1
    assert constraints.max_count == 5
    assert constraints.budget_inr == Decimal(20000)
    assert constraints.sector == "IT"
    assert constraints.profile_intent is True


def test_parser_returns_none_for_unbounded_research() -> None:
    assert parse_complex_question("What is the latest news for TCS?") is None


def test_parser_does_not_treat_within_as_the_it_sector() -> None:
    constraints = parse_complex_question("find 1 to 5 stocks within INR 20000")

    assert constraints is not None
    assert constraints.sector is None


def test_filter_and_allocator_enforce_sector_total_budget_and_maximum() -> None:
    constraints = parse_complex_question("find 1 to 3 technology stocks within INR 10000")
    assert constraints is not None
    candidates = [
        stock("TCS", "4125", "IT"),
        stock("INFY", "1842", "IT"),
        stock("ITC", "493", "FMCG"),
    ]

    eligible = filter_candidates(candidates, constraints)
    allocation = allocate_budget(eligible, constraints)

    assert [item.ticker for item in allocation.selected] == ["TCS", "INFY"]
    assert allocation.total_cost == Decimal(5967)
    assert allocation.shortfall is None


def test_allocator_reports_when_minimum_cannot_be_met() -> None:
    constraints = parse_complex_question("find 3 to 5 technology stocks within INR 1000")
    assert constraints is not None

    allocation = allocate_budget(
        filter_candidates([stock("TCS", "4125"), stock("INFY", "1842")], constraints),
        constraints,
    )

    assert allocation.selected == ()
    assert allocation.shortfall == "Only 0 of the requested minimum 3 stocks fit the INR 1000 total budget."
