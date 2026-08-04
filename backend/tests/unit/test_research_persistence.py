from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.domain.models import (
    Citation,
    ConversationMessage,
    DocumentKind,
    InvestorPersona,
    ResearchConversation,
    ResearchNote,
    SourceDocument,
    SourceTier,
)
from app.repositories.memory import InMemoryResearchRepository
from app.repositories.sql import SqlAlchemyResearchRepository, UserRow


class _AsyncContext:
    def __init__(self, value) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None


class _AdminRepositorySession:
    def __init__(self, user_exists: bool) -> None:
        self.user_exists = user_exists

    async def get(self, model, user_id: str):
        return UserRow(id=user_id) if self.user_exists else None

    async def execute(self, statement):
        return SimpleNamespace(rowcount=1)


class _AdminRepositorySessions:
    def __init__(self, user_exists: bool) -> None:
        self.session = _AdminRepositorySession(user_exists)

    def begin(self) -> _AsyncContext:
        return _AsyncContext(self.session)


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


@pytest.mark.asyncio
async def test_in_memory_research_citations_preserve_source_tier() -> None:
    repository = InMemoryResearchRepository()
    now = datetime.now(UTC)
    source = SourceDocument.create(
        ticker="TCS",
        kind=DocumentKind.NEWS,
        title="SEBI disclosure",
        url="https://www.sebi.gov.in/tcs-disclosure",
        content="TCS disclosure.",
        published_at=now,
        source_tier=SourceTier.PRIMARY,
    )
    conversation = ResearchConversation(
        id="tier-conversation", user_id="user-1", title="TCS", created_at=now, updated_at=now
    )
    citation = Citation(index=1, document_id=source.id, title=source.title, url=source.url, source_tier=source.source_tier)
    await repository.create_conversation(conversation)
    await repository.add_conversation_message(
        ConversationMessage(
            id="tier-message", conversation_id=conversation.id, role="assistant", text="SEBI disclosure [1].",
            citations=(citation,), created_at=now,
        )
    )

    messages = await repository.list_conversation_messages("user-1", conversation.id)

    assert messages[0].citations[0].source_tier is SourceTier.PRIMARY


@pytest.mark.asyncio
async def test_in_memory_conversation_title_update_preserves_ownership() -> None:
    repository = InMemoryResearchRepository()
    now = datetime.now(UTC)
    conversation = ResearchConversation(
        id="conversation-rename",
        user_id="user-1",
        title="Original",
        created_at=now,
        updated_at=now,
    )
    await repository.create_conversation(conversation)
    renamed = conversation.model_copy(update={"title": "Renamed"})

    await repository.update_conversation(renamed)

    assert (await repository.get_conversation("user-1", conversation.id)).title == "Renamed"
    assert await repository.get_conversation("user-2", conversation.id) is None


@pytest.mark.asyncio
async def test_in_memory_admin_resets_and_deletes_only_target_user_data() -> None:
    repository = InMemoryResearchRepository()
    await repository.initialize()
    now = datetime.now(UTC)
    await repository.upsert_user("target", "target@example.com", "Target", None)
    await repository.upsert_user("other", "other@example.com", "Other", None)
    await repository.follow_stock("target", "TCS")
    await repository.follow_stock("other", "INFY")
    persona = InvestorPersona(user_id="target", style="Target style")
    await repository.save_persona(persona, (1.0,))
    conversation = ResearchConversation(
        id="target-conversation",
        user_id="target",
        title="Target research",
        created_at=now,
        updated_at=now,
    )
    other_conversation = conversation.model_copy(
        update={"id": "other-conversation", "user_id": "other"}
    )
    await repository.create_conversation(conversation)
    await repository.create_conversation(other_conversation)
    await repository.add_conversation_message(
        ConversationMessage(
            id="target-message",
            conversation_id=conversation.id,
            role="user",
            text="Review TCS",
            created_at=now,
        )
    )

    assert await repository.reset_user_follows("missing") is False
    assert await repository.reset_user_profile("missing") is False
    assert await repository.delete_user_conversations("missing") is False
    assert await repository.reset_user_profile("target") is True
    assert await repository.list_followed_tickers("target") == ()
    assert (await repository.get_persona("target")).style != persona.style
    assert await repository.delete_user_conversations("target") is True
    assert await repository.list_conversations("target") == ()
    assert await repository.list_conversation_messages("target", conversation.id) == ()
    assert await repository.list_conversations("other") == (other_conversation,)
    assert await repository.list_followed_tickers("other") == ("INFY",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ("reset_user_profile", "reset_user_follows", "delete_user_conversations"),
)
async def test_sql_admin_repository_reports_missing_users(method_name: str) -> None:
    repository = object.__new__(SqlAlchemyResearchRepository)
    repository._sessions = cast(Any, _AdminRepositorySessions(user_exists=False))

    assert await getattr(repository, method_name)("missing") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ("reset_user_profile", "reset_user_follows", "delete_user_conversations"),
)
async def test_sql_admin_repository_applies_existing_user_mutations(method_name: str) -> None:
    repository = object.__new__(SqlAlchemyResearchRepository)
    repository._sessions = cast(Any, _AdminRepositorySessions(user_exists=True))

    assert await getattr(repository, method_name)("user-id") is True
