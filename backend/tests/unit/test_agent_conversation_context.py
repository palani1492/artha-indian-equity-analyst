from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import ConversationMessage


def _message(
    message_id: str,
    role: str,
    text: str,
    scope_tickers: tuple[str, ...] = (),
) -> ConversationMessage:
    return ConversationMessage(
        id=message_id,
        conversation_id="conversation-1",
        role=role,  # type: ignore[arg-type]
        text=text,
        scope_tickers=scope_tickers,
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ((_message("1", "user", "Latest news for TCS", ("TCS",)),), ("TCS",)),
        (
            (
                _message("1", "user", "Latest news for TCS", ("TCS",)),
                _message("2", "assistant", "Infosys is the answer", ("INFY",)),
            ),
            ("TCS",),
        ),
    ],
)
def test_history_scope_uses_prior_user_context_only(history, expected) -> None:
    from app.agent import EquityResearchAgent

    assert EquityResearchAgent._history_scope(history) == expected
