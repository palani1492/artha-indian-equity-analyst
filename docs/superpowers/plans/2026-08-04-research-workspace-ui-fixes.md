# Research Workspace UI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent, deterministic conversation renaming and deliver the requested notes, right-rail, admin, coverage, accessibility, and E2E fixes without breaking existing API contracts.

**Architecture:** Keep conversation title generation in the frontend as a pure deterministic function based on the first user message, then persist explicit edits through a new ownership-scoped PATCH endpoint. Extend the repository protocol and both repository implementations immutably. Keep notes and admin behavior in the existing workspace components, deriving coverage from non-zero indexed stock/document/source data with clear fallback rules.

**Tech Stack:** FastAPI, Pydantic, Python repository protocol, in-memory and SQLAlchemy repositories, React 19/TypeScript, Playwright.

## Global Constraints

- Use `apply_patch` for all manual edits.
- Do not deploy or change unrelated backend contracts.
- Validate and trim conversation titles at the API boundary; enforce authenticated ownership.
- Preserve responsive layout, keyboard access, semantic labels, and reduced-motion behavior.
- Run `npm run lint`, `npm run typecheck`, `npm test`, and `npm run test:e2e`.

---

### Task 1: Conversation Rename Contract

**Files:**
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/memory.py`
- Modify: `backend/app/repositories/sql.py`
- Modify: `backend/app/api.py`
- Test: `backend/tests/unit/test_research_persistence.py`
- Test: `backend/tests/integration/test_api.py`

**Interfaces:**
- Produce `ResearchRepository.update_conversation(conversation: ResearchConversation) -> None`.
- Produce `PATCH /api/v1/conversations/{conversation_id}` accepting `{ "title": string }` and returning `ResearchConversation`.
- Return `401` for unauthenticated requests, `404` for another user's or missing conversation, and `422` for blank/overlong titles.

- [ ] Write failing repository tests proving both repositories preserve ownership fields and update only the title plus `updated_at`.
- [ ] Write failing API tests for successful rename, blank/overlong validation, missing/foreign conversation ownership, and unauthenticated access.
- [ ] Run focused backend tests and confirm the new tests fail before implementation.
- [ ] Add `update_conversation` to the protocol and implement immutable replacement in memory and a transactional SQL row update.
- [ ] Add `ConversationPatchRequest` with `title` length bounds and whitespace trimming, then add the authenticated route using `get_conversation(user_id, conversation_id)` before updating.
- [ ] Run the focused backend tests and confirm they pass.

### Task 2: Conversation UX

**Files:**
- Modify: `app/artha-api.ts`
- Modify: `app/ArthaWorkspace.tsx`
- Modify: `app/styles/research.css`
- Modify: `app/styles/responsive.css` if required by the existing breakpoint rules
- Test: `e2e/workspace.spec.ts`

**Interfaces:**
- Produce a client `renameConversation(conversationId: string, title: string): Promise<ResearchConversation>` wrapper for the new PATCH endpoint.
- Produce a pure deterministic title helper that uses the first user message, trims whitespace, collapses internal whitespace, and caps the display/API title to the existing 200-character limit without using timestamps or random data.

- [ ] Add E2E coverage that starts from an empty/new conversation, sends the first user message, verifies the generated title, edits the title, reloads, and verifies persistence.
- [ ] Add E2E assertions that `New conversation` is an actionable button/state and not a permanent conversation title.
- [ ] Run the focused E2E test and confirm it fails against the current UI.
- [ ] On the first user message, derive the title only when the conversation has no user message and update the local conversation list immutably.
- [ ] Add accessible rename controls for the active conversation with edit, input, save, cancel, disabled/loading state, and a user-facing error notice.
- [ ] Make the new-conversation affordance create/select a conversation whose empty state is labeled as new rather than naming it permanently.
- [ ] Add the API wrapper and persist explicit/generated titles through the PATCH endpoint while preserving the current conversation selection and messages.
- [ ] Style the controls within existing responsive patterns and verify keyboard/focus behavior.
- [ ] Run the focused E2E test and confirm it passes.

### Task 3: Notes Delete Controls

**Files:**
- Modify: `app/artha-api.ts`
- Modify: `app/ArthaWorkspace.tsx`
- Modify: `app/styles/context.css`
- Test: `e2e/workspace.spec.ts`

**Interfaces:**
- Produce `deleteNote(noteId: string): Promise<void>` calling the existing `DELETE /api/v1/notes/{note_id}` endpoint.

- [ ] Add E2E coverage with a mocked authenticated notes response, confirm the delete control is labeled per note, cancel confirmation, then confirm deletion and verify the API request and removed row.
- [ ] Run the focused E2E test and confirm it fails because the control is absent.
- [ ] Add a delete button per note with an accessible name, `window.confirm` confirmation, pending state, immutable local removal only after success, and a specific failure notice.
- [ ] Add the API wrapper and preserve existing note creation behavior.
- [ ] Style the control for desktop/mobile hit targets without hiding it from keyboard or assistive technology.
- [ ] Run the focused E2E test and confirm it passes.

### Task 4: Right Rail Order and Coverage Counts

**Files:**
- Modify: `app/ArthaWorkspace.tsx`
- Modify: `app/artha-api.ts` if parsing needs a narrowly scoped source/document count field
- Modify: `app/styles/context.css` only if order-specific responsive styling requires it
- Test: `e2e/workspace.spec.ts`

**Interfaces:**
- Render the right rail in exactly this DOM order: `Investor memory`, `Coverage/Evidence matrix`, `Research notes`, `Sources`, `Admin`.
- Coverage counts must prefer actual source/document data, never replacing an available non-zero indexed/source count with `0`.

- [ ] Add E2E assertions for the exact section order and a fixture where `indexedDocuments` is non-zero while source data is present.
- [ ] Run the focused E2E test and confirm it fails against the current order/count behavior.
- [ ] Move the existing sections without changing their data contracts or responsive container behavior.
- [ ] Update `EvidenceMatrix` count derivation to use actual source list/document count fields first, then non-zero `indexedDocuments`, and only show zero when all available signals are genuinely empty.
- [ ] Ensure source arrays and stock data from both demo and live parsing feed the same count path.
- [ ] Run the focused E2E test and confirm it passes.

### Task 5: Admin Safety and Error Copy

**Files:**
- Modify: `app/ArthaWorkspace.tsx`
- Modify: `app/artha-api.ts` only if error status/detail parsing is needed
- Modify: `app/styles/context.css` if the admin-last layout needs existing styles adjusted
- Test: `e2e/admin.spec.ts`

**Interfaces:**
- Admin controls must not render destructive actions for the signed-in admin's own user row.
- A self-target `409` must produce a specific self-protection message; `401/403` must retain specific authentication/authorization messages.

- [ ] Add E2E coverage for a user list containing the signed-in admin and another user, verifying the admin row has no destructive controls while the other row does.
- [ ] Add E2E coverage for mocked `409`, `401`, and `403` action responses and assert their distinct messages.
- [ ] Run focused admin tests and confirm they fail against the current rendering/error behavior.
- [ ] Filter self-target rows/actions in the admin panel using the authenticated user's stable ID/email and preserve the panel for other users.
- [ ] Map `409` to explicit copy such as `You cannot reset or delete your own administrator account.` and retain separate expired-session and unauthorized messages.
- [ ] Verify Admin is the final right-rail section and all controls remain labeled and keyboard reachable.
- [ ] Run focused admin tests and confirm they pass.

### Task 6: Full Verification and Review

**Files:**
- No new files; inspect all changed files and existing dirty changes without reverting them.

- [ ] Run `npm run lint`.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm test`.
- [ ] Run `npm run test:e2e`.
- [ ] Run the backend test suite used by the repository (`pytest`) if the environment supports it.
- [ ] Review `git diff` for contract drift, hardcoded secrets, console logging, accessibility regressions, and accidental deployment changes.
