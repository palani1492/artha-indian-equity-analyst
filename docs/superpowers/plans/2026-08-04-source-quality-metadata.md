# Source Quality Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add validated source-quality tiers that survive ingestion, grounding, persistence, API serialization, and source UI rendering without changing provider behavior.

**Architecture:** Add a frozen `SourceTier` enum and defaulted fields to `SourceDocument` and `Citation`. Providers explicitly classify known source origins; all unspecified sources remain `secondary`. SQL stores the document tier in a migrated column, while citation JSON naturally preserves the tier through Pydantic serialization.

**Tech Stack:** Python 3, Pydantic, FastAPI, SQLAlchemy/Alembic, pytest, TypeScript/React.

## Global Constraints

- No external dependencies.
- Do not change provider fetch, parsing, deduplication, or ranking behavior.
- Do not invent new source URLs or claim direct NSE/BSE ingestion.
- Tiers are exactly `primary`, `company`, `secondary`, and `contextual`; default is `secondary`.
- SEBI-hosted entries are `primary`; company investor-relations URLs are `company`; other RSS/news and yfinance fundamentals are `secondary`.

---

### Task 1: Domain Contract and Provider Classification

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/providers.py`
- Test: `backend/tests/unit/test_models_and_settings.py`
- Test: `backend/tests/unit/test_live_provider.py`

**Interfaces:**
- Produces `SourceTier` and `SourceDocument.source_tier` / `Citation.source_tier` with default `SourceTier.SECONDARY`.
- Provider helper classifies only existing URL metadata and leaves all RSS parsing behavior unchanged.

- [ ] Write tests for enum validation/defaults, yfinance secondary tier, SEBI primary tier, company URL tier, and ordinary RSS secondary tier.
- [ ] Run the focused tests and confirm the new assertions fail.
- [ ] Add the enum and fields; pass `source_tier` explicitly only at existing provider construction points where classification is known.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Persistence and Migration

**Files:**
- Modify: `backend/app/repositories/sql.py`
- Create: `backend/alembic/versions/20260804_0005_source_tiers.py`
- Test: `backend/tests/unit/test_research_persistence.py`
- Test: `backend/tests/integration/test_sql_repository.py`

**Interfaces:**
- `DocumentRow.source_tier` stores the enum value as a non-null string with a `secondary` server default for existing rows.
- SQL document round-trips reconstruct the validated domain tier.

- [ ] Add repository/model tests that insert and retrieve a tiered source and preserve tiered citations in conversation/note JSON.
- [ ] Run focused persistence tests and confirm failure before implementation.
- [ ] Add the mapped column and Alembic upgrade/downgrade using a non-null `String(20)` column with default `secondary`.
- [ ] Run focused persistence tests and migration checks.

### Task 3: Grounding and API Serialization

**Files:**
- Modify: `backend/app/generation.py`
- Modify: `backend/app/agent.py`
- Modify: `backend/app/api.py`
- Modify: `app/artha-api.ts`
- Test: `backend/tests/unit/test_grounding.py`
- Test: `backend/tests/unit/test_agent_grounding.py`
- Test: `backend/tests/integration/test_api.py`

**Interfaces:**
- Citation builders copy `source.source_tier` into every citation.
- API responses and client parsing expose the same tier without changing citation IDs or labels.

- [ ] Add grounding tests asserting citations retain each source tier through generated answers and persisted message/note payloads.
- [ ] Run focused tests and confirm they fail.
- [ ] Copy the tier in all citation builders and add the client-side `SourceTier`/field parsing.
- [ ] Run focused backend and TypeScript checks.

### Task 4: Source UI Labels and Verification

**Files:**
- Modify: `app/artha-data.ts`
- Modify: `app/ArthaWorkspace.tsx`
- Test: `e2e/accessibility.spec.ts` or existing source UI coverage if available

**Interfaces:**
- `ResearchSource` and `Citation` expose `sourceTier`.
- Source cards render human-readable labels for all four tiers while preserving existing kind/publisher labels.

- [ ] Add source-tier label assertions to the UI test surface.
- [ ] Render a compact tier label with accessible text in source cards and citation source data.
- [ ] Run frontend lint/typecheck/build and relevant Playwright checks.

### Task 5: Full Verification

- [ ] Run backend `ruff`, `mypy`, full `pytest --cov` suite, and migration validation.
- [ ] Run frontend checks for touched TypeScript/React files.
- [ ] Review `git diff` and `git status`; do not deploy or commit unless explicitly requested.
