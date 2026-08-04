# Bounded Budget Allocation TDD Evidence

**Source plan:** `docs/superpowers/plans/2026-08-04-bounded-budget-allocation.md`

**User journeys:**

- A recommendation request finds a feasible subset when greedy selection would miss it.
- A recommendation request never exceeds the INR budget and can use it exactly.
- Sector and profile intent remain represented in constrained recommendation parsing and filtering.
- Equal-size feasible choices remain deterministic in ranked input order.
- An unmet minimum returns the existing shortfall response.

| Guarantee | Test | Result |
|---|---|---|
| Combination search finds `500 + 500` after greedy would choose `600` first | `tests/unit/test_complex_questions.py::test_allocator_finds_combination_greedy_selection_would_miss` | PASS |
| Exact budget totals and rank order are preserved | `tests/unit/test_complex_questions.py::test_allocator_uses_exact_budget_and_preserves_rank_order` | PASS |
| Sector and budget filters exclude ineligible stocks | `tests/unit/test_complex_questions.py::test_filter_excludes_other_sectors_and_over_budget_candidates` | PASS |
| Profile intent is preserved with sector constraints | `tests/unit/test_complex_questions.py::test_profile_intent_is_preserved_with_sector_constraints` | PASS |
| Insufficient feasible candidates return the existing shortfall | `tests/unit/test_complex_questions.py::test_allocator_reports_when_minimum_cannot_be_met` | PASS |

**RED evidence:** `pytest tests/unit/test_complex_questions.py -q` failed the greedy-miss regression with the expected empty selection.

**GREEN and verification evidence:**

- `pytest tests/unit/test_complex_questions.py -q`: 9 passed.
- `ruff check .`: all checks passed.
- `mypy app`: no issues found in 27 source files.
- `pytest --cov=app --cov-report=term-missing`: 140 passed, 1 skipped; total coverage 81.50%.

No deployment was performed.
