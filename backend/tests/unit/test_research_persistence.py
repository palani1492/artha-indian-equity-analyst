from datetime import UTC, datetime

import pytest

from app.domain.models import ConversationMessage, ResearchConversation, ResearchNote
from app.repositories.memory import InMemoryResearchRepository


@pytest.mark.asyncio
async def test_in_memory_research_data_isolated_by_user() -> None:
    repository = InMemoryResearchRepository()
    now = datetime.now(UTC)
    conversation = ResearchConversation(
        id="conversation-1",
        user_id="user-1",
        title="TCS",
        created_at=now,
        updated_at=now,
    )
    await repository.create_conversation(conversation)
    await repository.add_conversation_message(
        ConversationMessage(
            id="message-1",
            conversation_id=conversation.id,
            role="user",
            text="Review TCS",
            scope_tickers=("TCS",),
            created_at=now,
        )
    )
    assert await repository.list_conversation_messages("user-2", conversation.id) == ()
    assert (await repository.list_conversation_messages("user-1", conversation.id))[0].scope_tickers == ("TCS",)

    note = ResearchNote(
        id="note-1",
        user_id="user-1",
        title="Thesis",
        body="Validate margins.",
        created_at=now,
        updated_at=now,
    )
    await repository.create_note(note)
    assert await repository.get_note("user-2", note.id) is None
    assert await repository.delete_note("user-2", note.id) is False
    assert await repository.get_note("user-1", note.id) == note
