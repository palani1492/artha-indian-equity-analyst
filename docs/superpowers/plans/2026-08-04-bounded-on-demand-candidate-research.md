# Bounded On-Demand Candidate Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand complex sector-constrained recommendations with at most eight matching, not-yet-indexed ticker-directory candidates, while preserving user follows and isolating provider failures.

**Architecture:** Add a repository-wide stock listing protocol implemented by the in-memory and SQL repositories. During constrained recommendation retrieval, first use the user's indexed/followed stocks; if a sector constraint is present and that universe cannot satisfy the requested minimum, select up to eight deterministic directory entries absent from the indexed universe, ingest each independently through the existing `IngestionService`, then rank only successful ingestions together with existing candidates. Return metadata identifying on-demand indexing and concise failure limitations.

**Tech Stack:** Python 3.11, Pydantic, SQLAlchemy async repositories, pytest/pytest-cov, Ruff, mypy.

## Global Constraints

- Candidate universe is only the existing bundled ticker directory.
- At most 8 directory tickers may be selected or ingested per question.
- Candidates already indexed are excluded from on-demand ingestion.
- On-demand ingestion never calls `follow_stock` and never changes user ownership.
- Each candidate failure is isolated; successful candidates continue through ranking.
- No arbitrary universe crawl or deployment.

---

### Task 1: Add repository-wide stock listing

**Files:**
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/memory.py`
- Modify: `backend/app/repositories/sql.py`
- Test: `backend/tests/integration/test_sql_repository.py`

**Interfaces:**
- Produces `ResearchRepository.list_all_stocks() -> tuple[Stock, ...]`, ordered deterministically by ticker.

- [ ] **Step 1: Write the failing test**

Add an in-memory assertion in the existing repository tests or a focused unit test that inserts two stocks and verifies `list_all_stocks()` returns both in ticker order. Add the SQL repository equivalent alongside existing SQL repository behavior if the test fixture supports it.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd backend && pytest tests/integration/test_sql_repository.py -q`

Expected: collection or execution fails because the repository method is not defined.

- [ ] **Step 3: Write the minimal implementation**

Declare the async protocol method. In memory, return `Stock` values sorted by ticker. In SQL, select `StockRow` ordered by `StockRow.ticker` and convert rows with `_stock`.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd backend && pytest tests/integration/test_sql_repository.py -q`

Expected: PASS, or database-dependent tests are skipped according to the existing repository fixture behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/base.py backend/app/repositories/memory.py backend/app/repositories/sql.py backend/tests/integration/test_sql_repository.py
git commit -m "feat: list all indexed stocks"
```

### Task 2: Implement bounded candidate expansion and failure metadata

**Files:**
- Modify: `backend/app/agent.py`
- Modify: `backend/app/ticker_directory.py` only if a deterministic sector-filter helper is needed
- Test: `backend/tests/unit/test_agent.py` or the existing constrained-question test module

**Interfaces:**
- Consumes `ResearchRepository.list_all_stocks()` and `Container.ingestion` wiring through `EquityResearchAgent`.
- Produces constrained recommendation metadata with `universe`, `on_demand_indexed_tickers`, and `on_demand_failed_tickers`.

- [ ] **Step 1: Write failing tests**

Cover these behaviors:

```python
async def test_sector_constraint_indexes_directory_candidates_without_following_them(...):
    # followed/indexed universe is insufficient; one matching directory ticker succeeds
    # and appears in recommendations, while list_followed_tickers is unchanged.

async def test_on_demand_provider_failure_isolated_and_reported(...):
    # one candidate raises, another succeeds; successful candidate remains rankable and
    # metadata contains a concise failed-candidate limitation.

async def test_on_demand_candidate_selection_is_capped_at_eight(...):
    # provider call count never exceeds eight, even when the sector directory has more.
```

Use a recording/failing provider or replace the container ingestion service with a small async fake. Seed the repository with only the currently followed stock and assert no follow calls occur for candidate tickers.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_agent.py -q` (or the focused test node containing the new cases).

Expected: FAIL because constrained retrieval currently uses only `list_stocks_for_user` and has no on-demand metadata.

- [ ] **Step 3: Write the minimal implementation**

Inject the existing `IngestionService` into `EquityResearchAgent` and its container construction. In constrained retrieval:

1. Filter/rank existing indexed stocks first.
2. If a sector exists and the indexed eligible universe cannot meet `min_count`, call `list_all_stocks()` only to identify indexed tickers, then iterate the bundled `TICKER_DIRECTORY` in deterministic order.
3. Select matching-sector entries not in the indexed ticker set, cap at eight, and skip directory entries whose ticker is already indexed.
4. Await `ingestion.ingest(entry.ticker)` per candidate in a `try/except` limited to expected provider/ingestion failures; record failed tickers and continue.
5. Re-read successful stocks from the repository, combine them with existing stocks, filter by constraints, rank, allocate, and fetch fundamentals.
6. Preserve `follow_stock` as untouched code path and add metadata only for on-demand attempts. If failures exist, set `constraint_limitation` to a concise sentence only when the resulting allocation still misses the requested minimum; otherwise include the failure note in metadata without discarding successful results.

Use a constant for the maximum of eight and avoid fetching or crawling anything outside directory entries.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_agent.py -q` (or the focused test node).

Expected: PASS for candidate expansion, no-follow side effect, failure isolation, and eight-ticker bound.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent.py backend/app/container.py backend/tests/unit/test_agent.py
git commit -m "feat: add bounded on-demand research candidates"
```

### Task 3: Verify full behavior and static quality

**Files:**
- Modify: `backend/tests/unit/test_complex_questions.py` only if boundary coverage belongs there
- Create: `docs/testing/bounded-on-demand-candidate-research.tdd.md`

- [ ] **Step 1: Run formatting/lint and type checks**

Run: `cd backend && ruff check app tests && mypy app`

- [ ] **Step 2: Run the full coverage suite**

Run: `cd backend && pytest --cov=app --cov-report=term-missing`

Expected: all tests pass and coverage remains at least 80%.

- [ ] **Step 3: Review the diff for ownership and bounds**

Run: `git diff --check && git diff -- backend/app/agent.py backend/app/repositories/base.py backend/app/repositories/memory.py backend/app/repositories/sql.py`

Confirm no follow mutation, no unbounded directory iteration, no swallowed exceptions outside candidate isolation, and no deployment changes.

- [ ] **Step 4: Write the TDD evidence report**

Record the actual focused RED/GREEN commands, full verification commands, coverage result, and the four required guarantees: on-demand candidates, no-follow side effect, provider failure isolation, and the eight-candidate cap.
