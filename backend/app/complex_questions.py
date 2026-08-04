from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.domain.models import Stock

_COUNT_RANGE = re.compile(r"\b(\d+)\s*(?:to|-)\s*(\d+)\b", re.IGNORECASE)
_COUNT_MAX = re.compile(r"\b(?:up to|at most|max(?:imum)?(?: of)?)\s*(\d+)\b", re.IGNORECASE)
_BUDGET = re.compile(r"(?:\binr\b|₹|\brs\.?\b)\s*([\d,]+(?:\.\d+)?)\s*(k|lakh)?", re.IGNORECASE)
_SECTOR_ALIASES = {
    "technology": "IT",
    "tech": "IT",
    "it": "IT",
    "information technology": "IT",
    "banking": "Banking",
    "banks": "Banking",
    "financial": "Financial Services",
    "finance": "Financial Services",
    "fmcg": "FMCG",
    "energy": "Energy",
    "pharma": "Pharma",
    "healthcare": "Healthcare",
}


@dataclass(frozen=True, slots=True)
class ComplexQuestionConstraints:
    min_count: int = 1
    max_count: int = 5
    budget_inr: Decimal | None = None
    sector: str | None = None
    profile_intent: bool = False


@dataclass(frozen=True, slots=True)
class AllocationResult:
    selected: tuple[Stock, ...]
    total_cost: Decimal
    shortfall: str | None = None


def parse_complex_question(message: str) -> ComplexQuestionConstraints | None:
    normalized = " ".join(message.lower().split())
    count_match = _COUNT_RANGE.search(normalized)
    max_match = _COUNT_MAX.search(normalized)
    if count_match:
        minimum, maximum = int(count_match.group(1)), int(count_match.group(2))
    elif max_match:
        minimum, maximum = 1, int(max_match.group(1))
    else:
        minimum = maximum = 1

    budget_match = _BUDGET.search(normalized)
    budget = _parse_budget(budget_match) if budget_match else None
    sector = next(
        (
            canonical
            for alias, canonical in _SECTOR_ALIASES.items()
            if re.search(rf"\b{re.escape(alias)}\b", normalized)
        ),
        None,
    )
    profile_intent = any(
        phrase in normalized
        for phrase in ("my investor profile", "my profile", "investor profile", "fit my")
    )
    recommendation_intent = any(
        phrase in normalized
        for phrase in ("find", "recommend", "stocks", "picks", "ideas", "buy")
    )
    constrained = budget is not None or count_match is not None or sector is not None
    if not constrained or not recommendation_intent:
        return None
    if minimum < 1 or maximum < minimum:
        return None
    return ComplexQuestionConstraints(
        min_count=minimum,
        max_count=maximum,
        budget_inr=budget,
        sector=sector,
        profile_intent=profile_intent,
    )


def filter_candidates(
    candidates: tuple[Stock, ...] | list[Stock],
    constraints: ComplexQuestionConstraints,
) -> tuple[Stock, ...]:
    sector = constraints.sector.casefold() if constraints.sector else None
    return tuple(
        stock
        for stock in candidates
        if stock.price_inr > 0
        and (sector is None or stock.sector.casefold() == sector)
        and (
            constraints.budget_inr is None
            or stock.price_inr <= constraints.budget_inr
        )
    )


def allocate_budget(
    candidates: tuple[Stock, ...] | list[Stock],
    constraints: ComplexQuestionConstraints,
) -> AllocationResult:
    if constraints.budget_inr is None:
        chosen = tuple(candidates[: constraints.max_count])
        return AllocationResult(chosen, sum((stock.price_inr for stock in chosen), Decimal(0)))

    remaining = constraints.budget_inr
    selected: list[Stock] = []
    for stock in candidates:
        if len(selected) >= constraints.max_count:
            break
        if stock.price_inr <= remaining:
            selected.append(stock)
            remaining -= stock.price_inr
    total = constraints.budget_inr - remaining
    shortfall = None
    if len(selected) < constraints.min_count:
        shortfall = (
            f"Only {len(selected)} of the requested minimum {constraints.min_count} "
            f"stocks fit the INR {constraints.budget_inr} total budget."
        )
        return AllocationResult((), Decimal(0), shortfall)
    return AllocationResult(tuple(selected), total)


def _parse_budget(match: re.Match[str]) -> Decimal | None:
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        value *= Decimal(1000)
    elif suffix == "lakh":
        value *= Decimal(100000)
    return value if value > 0 else None
