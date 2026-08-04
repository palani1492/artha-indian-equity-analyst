# Bounded Budget Allocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace greedy budget allocation with a small, deterministic combination search that finds the best feasible subset within the requested count and INR budget bounds.

**Architecture:** Keep filtering and the public `allocate_budget` interface unchanged. For budgeted allocations, enumerate combinations from a bounded candidate prefix and count range, selecting the feasible combination with the greatest count and then the earliest input-rank tuple; ranked candidates already encode score/coverage preference upstream.

**Tech Stack:** Python 3.11, pytest, coverage, ruff, mypy.

## Global Constraints

- Candidate and count search bounds remain small and safe.
- Allocation must be deterministic and must not mutate candidates.
- Existing shortfall text and no-budget behavior remain compatible.
- No deployment or external service changes.

---

### Task 1: Add allocator regression coverage

**Files:**
- Modify: `backend/tests/unit/test_complex_questions.py`

**Interfaces:**
- Consumes: existing `allocate_budget`, `filter_candidates`, and `ComplexQuestionConstraints` interfaces.
- Produces: tests for combination feasibility, exact budget use, shortfall behavior, filters, and stable ordering.

- [ ] **Step 1: Add a test where greedy selection misses a feasible pair.**
- [ ] **Step 2: Add exact-budget and deterministic-order assertions.**
- [ ] **Step 3: Run the focused tests and confirm the new combination test fails against the greedy implementation.**

### Task 2: Implement bounded deterministic search

**Files:**
- Modify: `backend/app/complex_questions.py:104-128`

**Interfaces:**
- Consumes: ordered `Stock` candidates and `ComplexQuestionConstraints`.
- Produces: the existing `AllocationResult` with selected candidates, total cost, or the existing shortfall message.

- [ ] **Step 1: Add small module-level candidate/count bounds.**
- [ ] **Step 2: Enumerate bounded combinations within the budget and requested count range.**
- [ ] **Step 3: Select by maximum count, then input-rank order, with exact `Decimal` totals.**
- [ ] **Step 4: Preserve no-budget behavior and shortfall semantics.**
- [ ] **Step 5: Run focused tests and then the full verification suite.**
