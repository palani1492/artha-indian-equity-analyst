# Bounded On-Demand Candidate Research TDD Evidence

## Source Plan

`docs/superpowers/plans/2026-08-04-bounded-on-demand-candidate-research.md`

## User Journeys

- As an investor, I want a sector-constrained question to search a bounded set of directory candidates when my followed universe is insufficient.
- As an investor, I want successful on-demand candidates ranked without changing my followed list.
- As an investor, I want one provider failure not to prevent other candidates from being considered.
- As an operator, I want candidate research capped at eight directory tickers per question.

## TDD Evidence

The focused candidate tests initially failed because `list_all_stocks`, agent ingestion wiring, and on-demand metadata did not exist. After implementation, the focused suite passed.

| Guarantee | Test | Result |
|---|---|---|
| Successful directory candidates are ranked without a follow side effect | `tests/unit/test_on_demand_candidates.py::test_on_demand_candidates_are_ranked_without_follow_side_effect` | PASS |
| A failed candidate is isolated and reported while a later candidate succeeds | `tests/unit/test_on_demand_candidates.py::test_on_demand_failure_isolated_and_reported` | PASS |
| Candidate ingestion is capped at eight attempts | `tests/unit/test_on_demand_candidates.py::test_on_demand_candidate_selection_is_capped_at_eight` | PASS |
| Repository-wide indexed stocks are listed deterministically | `tests/unit/test_on_demand_candidates.py::test_list_all_stocks_returns_indexed_stocks_in_ticker_order` | PASS |

## Verification

- `cd backend && ruff check app tests` -> passed.
- `cd backend && mypy app` -> passed.
- `cd backend && pytest --cov=app --cov-report=term-missing` -> 144 passed, 1 skipped; coverage 82.19%.
- `git diff --check` -> passed.

## Known Gaps

- The SQL repository integration test remains environment-gated by `TEST_DATABASE_URL`; the implementation is covered by the SQL repository code path and static checks, but no PostgreSQL instance was available in this run.
- Existing FastAPI/httpx deprecation warnings remain unrelated to this feature.
