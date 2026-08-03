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
            updates["style"] = "Dividend and quality"
        avoid_debt = bool(
            re.search(
                r"(?:avoid|exclude|don't want|do not want).{0,25}(?:high[- ]debt|debt)",
                normalized,
            )
        )
        prefers_low_debt = any(
            phrase in normalized
            for phrase in (
                "low debt",
                "low-debt",
                "low leverage",
                "low-leverage",
                "less debt",
            )
        )
        if (avoid_debt or prefers_low_debt) and not current.avoid_high_debt:
            updates["avoid_high_debt"] = True
            updates["max_debt_to_equity"] = min(current.max_debt_to_equity, Decimal(1))
        style = self._extract_style(normalized)
        if style is not None and style != current.style:
            updates["style"] = style
        horizon = self._extract_horizon(normalized)
        if horizon is not None and horizon != current.horizon:
            updates["horizon"] = horizon
        priorities = set(current.priorities)
        avoid = set(current.avoid)
        if prefers_low_debt:
            priorities.add("Low leverage")
            avoid.add("High debt")
        if any(
            phrase in normalized
            for phrase in (
                "durable cash flow",
                "durable cashflow",
                "stable cash flow",
                "predictable cash flow",
            )
        ):
            priorities.add("Durable cash flows")
        if "governance" in normalized:
            priorities.add("Governance")
        if dividend:
            priorities.add("Reliable dividends")
        if priorities != set(current.priorities):
            updates["priorities"] = tuple(sorted(priorities))
        if avoid != set(current.avoid):
            updates["avoid"] = tuple(sorted(avoid))
        sectors = self._extract_preferred_sectors(normalized)
        merged_sectors = tuple(sorted(set(current.preferred_sectors).union(sectors)))
        if merged_sectors != current.preferred_sectors:
            updates["preferred_sectors"] = merged_sectors
        note = self._memory_note(normalized)
        if note and note not in current.notes:
            updates["notes"] = (*current.notes[-4:], note)
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

    @staticmethod
    def _extract_style(message: str) -> str | None:
        if "quality at a fair price" in message or "qarp" in message:
            return "Quality at a fair price"
        if "dividend" in message:
            return "Dividend and quality"
        if "growth" in message:
            return "Growth"
        if "value" in message:
            return "Value"
        return None

    @staticmethod
    def _extract_horizon(message: str) -> str | None:
        if re.search(r"\bunder\s+1\s+year\b|\bshort[- ]term\b", message):
            return "Under 1 year"
        if re.search(r"\b1\s*(?:to|-)\s*3\s+years?\b", message):
            return "1 to 3 years"
        if re.search(r"\b3\s*(?:to|-)\s*5\s+years?\b", message):
            return "3 to 5 years"
        if re.search(r"\b5\+?\s+years?\b|\blong[- ]term\b", message):
            return "5+ years"
        return None

    @staticmethod
    def _memory_note(message: str) -> str | None:
        useful = any(
            phrase in message
            for phrase in (
                "i am",
                "i'm",
                "i prefer",
                "i avoid",
                "remember",
                "my horizon",
                "risk",
            )
        )
        return message[:240] if useful else None


def persona_as_text(persona: InvestorPersona) -> str:
    sectors = ", ".join(persona.preferred_sectors) or "no sector preference"
    return (
        f"Risk tolerance: {persona.risk_tolerance}. Style: {persona.style}. "
        f"Dividend focused: {persona.dividend_focused}. "
        f"Avoid high debt: {persona.avoid_high_debt}. Maximum debt to equity: "
        f"{persona.max_debt_to_equity}. Preferred sectors: {sectors}. "
        f"Priorities: {', '.join(persona.priorities) or 'none'}. "
        f"Avoid: {', '.join(persona.avoid) or 'none'}. Horizon: {persona.horizon}."
    )
