# Grounded Complex Question Workflow Implementation Plan

> **For agentic workers:** Execute this plan inline with tests after each focused change.

**Goal:** Parse bounded stock-selection questions deterministically, filter and allocate only from the followed/indexed universe, and produce citation-backed analyst prose without bypassing grounding.

**Architecture:** Add a focused constraint parser and allocator module. The existing LangGraph agent will detect constrained recommendations, apply sector and total-budget constraints before ranking/generation, and return an explicit limitation when the minimum cannot be met. Gemini remains an optional prose rewrite behind claim preservation and the existing grounding guard.

**Tech Stack:** Python, Pydantic, LangGraph, pytest, ruff, mypy, Gemini mock client.

## Global Constraints

- INR budget is the total across selected stocks, not a per-stock ceiling.
- Candidates come only from followed stocks with indexed stock data.
- Never invent candidates or bypass the grounding guard.
- Deterministic parsing, filtering, ranking, and allocation.
- Preserve authoritative claims, numbers, and citation markers through Gemini rewriting.

### Task 1: Add deterministic constraint parsing and allocation

**Files:**
- Create: `backend/app/complex_questions.py`
- Test: `backend/tests/unit/test_complex_questions.py`

- [ ] Write parser tests for count ranges, INR totals, sector extraction, profile intent, and ordinary prompts.
- [ ] Write allocator tests for sector filtering, total-budget enforcement, maximum count, and insufficient minimum count.
- [ ] Implement immutable request/result models and deterministic regex parsing.
- [ ] Implement sector filtering and rank-order greedy allocation with `Decimal` arithmetic.
- [ ] Run the focused unit tests.

### Task 2: Integrate constrained recommendations into the agent

**Files:**
- Modify: `backend/app/agent.py`
- Test: `backend/tests/integration/test_api.py`

- [ ] Add parsed constraints to agent state and classify natural constrained recommendation prompts.
- [ ] Filter followed/indexed stocks before ranking and select only within the total budget.
- [ ] Add explicit limitation drafts when the requested minimum cannot be met.
- [ ] Add readable conclusion, fit, risks, limitations, and citation-backed recommendation sections.
- [ ] Preserve response metadata through `ChatResult.answer_kind` and `metadata`.
- [ ] Add integration tests for successful constrained selection and insufficient followed data.
- [ ] Run focused integration tests.

### Task 3: Strengthen Gemini prose prompt and mock-client tests

**Files:**
- Modify: `backend/app/generation.py`
- Test: `backend/tests/unit/test_generation.py`

- [ ] Test that Gemini receives explicit analyst-section instructions and quoted source data.
- [ ] Test that the mock client output is returned to the claim-preserving wrapper.
- [ ] Update the prompt to request natural prose while preserving authoritative claims, numbers, currencies, and citations.
- [ ] Run generation tests.

### Task 4: Full verification

- [ ] Run `ruff check backend`.
- [ ] Run `mypy backend/app`.
- [ ] Run full pytest with coverage.
- [ ] Fix failures without weakening grounding or changing unrelated worktree changes.
