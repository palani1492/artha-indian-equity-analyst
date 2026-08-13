from __future__ import annotations

from app.domain.models import InvestorPersona, RiskTolerance
from app.persona import PersonaExtractor


def test_persona_is_learned_from_natural_language_without_losing_existing_data() -> (
    None
):
    current = InvestorPersona(user_id="u1", preferred_sectors=("IT",))
    updated, changed = PersonaExtractor().update(
        current,
        "I'm a conservative, dividend-focused investor. I avoid high debt companies and prefer FMCG.",
    )

    assert changed is True
    assert updated.risk_tolerance is RiskTolerance.CONSERVATIVE
    assert updated.dividend_focused is True
    assert updated.avoid_high_debt is True
    assert updated.preferred_sectors == ("FMCG", "IT")
    assert updated.version == current.version + 1
    assert current.risk_tolerance is RiskTolerance.BALANCED


def test_irrelevant_chat_does_not_mutate_or_version_persona() -> None:
    current = InvestorPersona(user_id="u1")
    updated, changed = PersonaExtractor().update(
        current, "What happened to TCS this week?"
    )
    assert changed is False
    assert updated == current


def test_risk_question_does_not_update_investor_memory() -> None:
    current = InvestorPersona(user_id="u1")
    updated, changed = PersonaExtractor().update(
        current, "What are the main risks for TCS right now?"
    )

    assert changed is False
    assert updated == current
