# LangGraph Conversation Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Load a bounded, user-owned conversation history into LangGraph so follow-up questions resolve prior entity scope without treating assistant claims as evidence.

**Architecture:** The chat API validates the conversation through the existing repository ownership boundary, reads the last eight persisted messages before writing the current user turn, and passes that history into the agent. The agent uses only prior user scope metadata and user text for resolution; indexed retrieval remains the sole evidence path and existing no-conversation, compatibility, and demo behavior remain unchanged.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, LangGraph, pytest, pytest-cov, ruff, mypy.

## Global Constraints

- Preserve both `/api/v1/chat` and `/api/chat` request compatibility.
- Keep demo mode deterministic and isolated.
- A conversation ID must be owned by the authenticated user or return `404`.
- Prior assistant messages are context only and never retrieval evidence or citations.
- History is bounded to the most recent 8 persisted messages.
- Run `ruff`, `mypy`, and `pytest` with coverage; do not deploy.

### Task 1: Add bounded history to the agent state

**Files:**
- Modify: `backend/app/agent.py`
- Test: `backend/tests/unit/test_agent_conversation_context.py`

**Interfaces:**
- Consume `ConversationMessage` values from `app.domain.models`.
- Produce `EquityResearchAgent.chat(..., conversation_history=tuple[ConversationMessage, ...])` while retaining existing callers.

- [ ] **Step 1: Write failing tests** for resolving a pronoun follow-up from the latest prior user scope, limiting history to eight messages at the API boundary passed to the agent, and ignoring assistant-only scope/evidence.
- [ ] **Step 2: Run the focused tests** with `pytest backend/tests/unit/test_agent_conversation_context.py -q`; confirm the new behavior fails.
- [ ] **Step 3: Implement** the optional history state field and a small helper that derives fallback scope from prior user messages/scope metadata only. Use it only when the current request has no explicit scope or entity, and leave source retrieval unchanged.
- [ ] **Step 4: Run the focused tests** again and confirm they pass.

### Task 2: Load and validate history in the chat API

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/integration/test_conversation_context.py`

**Interfaces:**
- Consume `repository.get_conversation` and `repository.list_conversation_messages` with the authenticated user ID.
- Produce an agent call containing `conversation_history=messages[-8:]` before the current user message is persisted.

- [ ] **Step 1: Write failing integration tests** for “what about that?” after a scoped turn, exactly eight-message bounding, and rejection of a conversation owned by another user.
- [ ] **Step 2: Run the focused integration tests** with `pytest backend/tests/integration/test_conversation_context.py -q`; confirm they fail.
- [ ] **Step 3: Implement** history loading after ownership validation and before inserting the current user message. Pass the bounded tuple into the agent; keep new conversation creation and both compatibility routes unchanged.
- [ ] **Step 4: Run the focused integration tests** and the existing API/multi-ticker tests; confirm all pass.

### Task 3: Full verification and review

**Files:**
- Review: `backend/app/agent.py`, `backend/app/api.py`, and the added tests.

- [ ] **Step 1: Run `ruff check backend`** and fix reported issues.
- [ ] **Step 2: Run `mypy backend/app`** and fix reported type errors.
- [ ] **Step 3: Run `pytest backend/tests --cov=backend/app --cov-report=term-missing`** and confirm the suite passes with coverage output.
- [ ] **Step 4: Inspect `git diff` and verify** no deployment command, API compatibility regression, assistant-evidence path, or unbounded history remains.
