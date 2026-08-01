from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from app.domain.models import InvestorPersona, RiskTolerance

SECTORS = {
    "banking": "Banking",
    "banks": "Banking",
    "fmcg": "FMCG",
    "consumer": "FMCG",
    "it": "IT",
    "technology": "IT",
    "energy": "Energy",
    "pharma": "Pharma",
    "healthcare": "Pharma",
    "auto": "Automobile",
    "automobile": "Automobile",
}


class PersonaExtractor:
    """Rule-based memory extraction keeps common persona updates cheap and testable."""

    def update(
        self, current: InvestorPersona, message: str
    ) -> tuple[InvestorPersona, bool]:
        normalized = " ".join(message.lower().split())
        updates: dict[str, object] = {}
        risk = self._extract_risk(normalized)
        if risk is not None and risk is not current.risk_tolerance:
            updates["risk_tolerance"] = risk
        dividend = any(
            phrase in normalized
            for phrase in (
                "dividend focused",
                "dividend-focused",
                "prefer dividends",
                "income investor",
            )
        )
        if dividend and not current.dividend_focused:
            updates["dividend_focused"] = True
        avoid_debt = bool(
            re.search(
                r"(?:avoid|exclude|don't want|do not want).{0,25}(?:high[- ]debt|debt)",
                normalized,
            )
        )
        if avoid_debt and not current.avoid_high_debt:
            updates["avoid_high_debt"] = True
            updates["max_debt_to_equity"] = min(current.max_debt_to_equity, Decimal(1))
        sectors = self._extract_preferred_sectors(normalized)
        merged_sectors = tuple(sorted(set(current.preferred_sectors).union(sectors)))
        if merged_sectors != current.preferred_sectors:
            updates["preferred_sectors"] = merged_sectors
        if not updates:
            return current, False
        return current.model_copy(
            update={
                **updates,
                "version": current.version + 1,
                "updated_at": datetime.now(UTC),
            }
        ), True

    @staticmethod
    def _extract_risk(message: str) -> RiskTolerance | None:
        if any(
            word in message
            for word in ("conservative", "low risk", "risk-averse", "risk averse")
        ):
            return RiskTolerance.CONSERVATIVE
        if any(
            word in message
            for word in ("aggressive", "high risk", "risk-seeking", "risk seeking")
        ):
            return RiskTolerance.AGGRESSIVE
        if "balanced" in message or "moderate risk" in message:
            return RiskTolerance.BALANCED
        return None

    @staticmethod
    def _extract_preferred_sectors(message: str) -> tuple[str, ...]:
        if not any(
            word in message for word in ("prefer", "focus", "like", "favour", "favor")
        ):
            return ()
        return tuple(
            sorted(
                {
                    canonical
                    for keyword, canonical in SECTORS.items()
                    if re.search(rf"\b{re.escape(keyword)}\b", message)
                }
            )
        )


def persona_as_text(persona: InvestorPersona) -> str:
    sectors = ", ".join(persona.preferred_sectors) or "no sector preference"
    return (
        f"Risk tolerance: {persona.risk_tolerance}. Dividend focused: {persona.dividend_focused}. "
        f"Avoid high debt: {persona.avoid_high_debt}. Maximum debt to equity: "
        f"{persona.max_debt_to_equity}. Preferred sectors: {sectors}. Horizon: {persona.horizon}."
    )
