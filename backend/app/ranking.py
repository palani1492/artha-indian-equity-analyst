from __future__ import annotations

from decimal import Decimal

from app.domain.models import InvestorPersona, RankedStock, RiskTolerance, Stock


class StockRanker:
    """Transparent O(n log n) persona ranker; no per-stock LLM calls."""

    def rank(
        self,
        persona: InvestorPersona,
        candidates: list[Stock] | tuple[Stock, ...],
        limit: int = 5,
    ) -> tuple[RankedStock, ...]:
        ranked: list[RankedStock] = []
        for stock in candidates:
            if self._excluded(persona, stock):
                continue
            score, reasons = self._score(persona, stock)
            ranked.append(
                RankedStock(stock=stock, score=round(score, 4), reasons=tuple(reasons))
            )
        ranked.sort(key=lambda item: (-item.score, item.stock.ticker))
        return tuple(ranked[:limit])

    @staticmethod
    def _excluded(persona: InvestorPersona, stock: Stock) -> bool:
        if stock.sector in persona.excluded_sectors:
            return True
        return bool(
            persona.avoid_high_debt
            and stock.debt_to_equity is not None
            and stock.debt_to_equity > persona.max_debt_to_equity
        )

    def _score(self, persona: InvestorPersona, stock: Stock) -> tuple[float, list[str]]:
        debt_score = self._inverse_ratio(stock.debt_to_equity, Decimal(2))
        dividend_score = self._bounded(stock.dividend_yield, Decimal(5))
        growth_score = self._bounded(stock.revenue_growth, Decimal(25))
        quality_score = self._bounded(stock.roe, Decimal(30))
        sentiment_score = (stock.sentiment + 1) / 2
        weights = self._weights(persona.risk_tolerance, persona.dividend_focused)
        score = (
            debt_score * weights[0]
            + dividend_score * weights[1]
            + growth_score * weights[2]
            + quality_score * weights[3]
            + sentiment_score * weights[4]
        )
        reasons: list[str] = []
        if debt_score >= 0.7:
            reasons.append("low leverage")
        if persona.dividend_focused and dividend_score >= 0.4:
            reasons.append("persona-aligned dividend yield")
        if growth_score >= 0.5:
            reasons.append("revenue growth")
        if quality_score >= 0.5:
            reasons.append("return-on-equity quality")
        if sentiment_score >= 0.6:
            reasons.append("constructive recent sentiment")
        return score, reasons or ["best available fit in the followed universe"]

    @staticmethod
    def _weights(
        risk: RiskTolerance, dividend_focused: bool
    ) -> tuple[float, float, float, float, float]:
        weights = {
            RiskTolerance.CONSERVATIVE: (0.35, 0.25, 0.10, 0.20, 0.10),
            RiskTolerance.BALANCED: (0.20, 0.15, 0.25, 0.20, 0.20),
            RiskTolerance.AGGRESSIVE: (0.10, 0.05, 0.40, 0.15, 0.30),
        }[risk]
        if not dividend_focused:
            return weights
        shifted = (
            weights[0],
            weights[1] + 0.10,
            max(0, weights[2] - 0.05),
            weights[3],
            max(0, weights[4] - 0.05),
        )
        total = sum(shifted)
        return tuple(value / total for value in shifted)  # type: ignore[return-value]

    @staticmethod
    def _bounded(value: Decimal | None, target: Decimal) -> float:
        return max(0.0, min(1.0, float(value / target))) if value is not None else 0.0

    @staticmethod
    def _inverse_ratio(value: Decimal | None, ceiling: Decimal) -> float:
        return max(0.0, 1.0 - float(value / ceiling)) if value is not None else 0.0
