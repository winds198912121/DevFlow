---
title: 'Refactor sweep — consolidate retry engine + bench query + skill bump registry (Story 3.10)'
type: 'refactor'
ticket: '10'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '711ce41'
---

<frozen-after-approval reason="human-owned intent — cleanup only; the ticket's own rule pushes new scope to a new story">

## Intent

Clean up Epic 3's surfaces without changing any story 1–9 verify line. The
ticket named three likely targets: the rung-resolution table, the
metric-definition schema for benchmark runs, and the error_store / event_log
migration runner.

Scope was set when the entry started, from the build records and the review
findings deferred during the epic.

## Boundaries & Constraints

**In scope:** deduplication and single-sourcing in existing Epic 3 code; small
correctness fixes where a duplicate had already drifted or a guard was missing.

**Out of scope (per the ticket's rule: "scope pushed out of stories 1–9 is a new
story"):** new features, new integrations, new CLI surface.

**Hard constraint:** no behavior change to stories 1–9's verify lines. Every
change below either removes a duplicate or fixes a path that raised.

## Findings & Changes

| # | Target | Finding (evidence) | Change |
|---|--------|--------------------|--------|
| 1 | migration runner (c) | All **13** tables were defined twice: once in `migrate._MIGRATIONS`, once as a hand-copied `CREATE TABLE IF NOT EXISTS` in a store's `_ensure_table`. Already drifted: `run_event_log`'s copy omitted `idx_run_events_run_id`, the index `list_for_run` needs. | `migrate.ensure_tables(db, *names)` derives DDL from `_MIGRATIONS`; all 9 helpers (8 stores + `herdr_ingest`) delegate. Removes 13 duplicate DDL bodies. |
| 2 | metric-definition schema (b) | `bench_query` guarded mixed **contracts** but not mixed **metric definitions** — and its own comment claims it does. It read `metric_definition` from row 0 while averaging all rows, so a cell mixing definitions returned the mean of incomparable numbers, labelled with whichever definition sorted first. | Raise `NonComparableSet` on mixed definitions, checked once for both query branches. |
| 3 | rung-resolution table (a) | `_STEP_CATEGORY_MAP` was a hand-copied identity dict of `STEP_ORDER` — a third copy of the step list. It had already produced a live bug: `delivery` is a pipeline step but **not** an Error Store category, so `advance(step="delivery")` raised `InvalidErrorCategory` instead of recording the rung. | Derive the category from the closed enum (`get_args(ErrorCategory)`); `delivery` now falls back to `coding`. |
| 4 | bench query (b) | Dead placeholder `metric_def = "see-row"` and a branch-local `metric_def` assignment duplicated in both branches. | Computed once after the guard. |

## I/O & Edge-Case Matrix

| Input | Before | After |
| --- | --- | --- |
| `bench_query` on a cell mixing metric definitions | mean of incomparable values, mislabelled | `NonComparableSet` |
| `bench_query` on a uniform cell | mean | mean (unchanged) |
| `bench_query` with 0 rows and `k=0` | `metric_definition="see-row"` | `""` (a nonsense placeholder removed; `k>=1` calls raise `BenchInsufficient` first, so this is unreachable in practice) |
| `advance(step="delivery")` | `InvalidErrorCategory` | records the rung, category `coding` |
| `advance(step="tool")` | category `coding` (collapsed) | category `tool` (it is a valid category) |
| `ensure_tables(db, "not_a_table")` | n/a | `ValueError` |
| A database bootstrapped without migrations | `run_events` missing its index | schema identical to the migrated one |
| `run --inject-failure-at coding` | flag did not exist | exits 0; one Error Store row with `retry[0].rung == 1` |
| `run --inject-failure-at delivery` | n/a | exits 0; recorded category is a closed-enum member |
| `run --inject-failure-at nope` | n/a | `unknown_step` on stderr, exit 2, no run performed |
| `run` without the flag | no Error Store rows | unchanged — no Error Store rows |

## Code Map

| File | Change |
| --- | --- |
| `harness/migrate.py` | Add `ensure_tables()` + `_statements_by_table()`, derived from `_MIGRATIONS` |
| `harness/{error_store,run_event_log,regression_set,cost_ledger,cost_guard,project_edit_lock,skill_bump_registry,executor_swap,herdr_ingest}.py` | `_ensure_table(s)` delegate to `migrate.ensure_tables` |
| `harness/regression_set.py` | Metric-definition comparability guard; `metric_definition` computed once |
| `harness/retry_ladder.py` | Drop `_STEP_CATEGORY_MAP`; `_step_category` reads the closed enum |
| `harness/cli.py` | `run --inject-failure-at STEP` (the ladder's first production caller); walk `STEP_ORDER` instead of a 4th inline copy of it |
| `tests/test_migrate.py` | +5 tests: bootstrap schema equals migrated schema, the restored index, unknown-table refusal, one-statement-per-migration |
| `tests/test_regression_set.py` | +2 tests: mixed definitions refuse; uniform definitions still average |
| `tests/test_retry_ladder.py` | +3 tests: every pipeline step yields an accepted category; `delivery` records a rung; fallback behaviour |
| `tests/test_cli.py` | +4 tests: the flag records a rung and exits 0; `delivery` records a valid category through the CLI; the flag is inert without it; an unknown step is refused with exit 2 |

## Tasks & Acceptance

- [x] Target (a) rung resolution — investigate, dedupe the step→category copy.
- [x] Target (b) metric-definition schema — add the missing comparability guard.
- [x] Target (c) migration runner — one definition for every table.
- [x] Target (d, from the verify line) — wire `run --inject-failure-at STEP`, the ladder's first production caller.
- [x] No behavior change to stories 1–9.

## Implementation Notes

**Decision (rung dispatch stays an if/elif).** The ticket suggested a
rung-resolution *table*. Inspected and rejected: the rungs do not share a
signature (`rung_3` needs `step`/`tier`, `rung_4` needs the skill pin and can
raise `SkillRegressionMissing`, rung 5 never resolves), so a dict of
`**_`-absorbing callables would hide exactly the differences that matter — the
refusal path and the terminal rung. The chain is honest about them. The real
duplication was the step→category list (finding 3), which is fixed.

**Decision (`_step_category` reads the enum, not `STEP_ORDER`).** Deriving from
`STEP_ORDER` would have preserved the old fallback semantics exactly but adds a
`workflow_controller` import, which triggers its boot-time pipeline load. Reading
`get_args(ErrorCategory)` keeps the module dependency-free *and* makes the
returned value structurally valid — the property `error_store.append` actually
enforces. The side effect is that `delivery` (a step, not a category) now
resolves to `coding` instead of raising.

**KEEP:** `ensure_tables` must stay derived from `_MIGRATIONS`; a store adding a
hand-copied `CREATE TABLE` re-introduces the drift `test_ensure_tables_produces_
the_migrated_schema` exists to catch. `bench_query` must check comparability on
**both** axes before averaging. `run --inject-failure-at` must leave the run
exiting 0 — a failure a run cannot survive is not what the ladder is for.

## Plan Change Log

- **2026-09-28:** Entry start. Scope set from Epic 3 build records: the three
  named targets were all real; two of the three had already produced defects
  (findings 1 and 3), which is why this is a fix-bearing sweep rather than pure
  reshuffling.
- **2026-09-28 (follow-up):** Wired `run --inject-failure-at STEP`. The verify
  line named it, and investigation showed `retry_ladder.advance` had **no
  production caller** — so the flag is not a test-only convenience, it is the
  ladder's first integration point. Two consequences recorded: the ladder is now
  exercised end-to-end by CI, and `run_command`'s inline re-listing of the six
  step names (a 4th copy of `STEP_ORDER`) is gone.

  Caveat for anyone running the verify line by hand: the python-hello fixture is
  `mode: human`, so `harness run` prompts on stdin. Non-interactively it needs
  piped input (`yes x | uv run harness run …`); without it the run fails at the
  first step with `executor_invocation_failed: operator_input_eof`. That is
  pre-existing behaviour of the human adapter, not of this flag.

## Review Triage Log

Self-review: 2 high (patched) / 1 medium (patched) / 1 noted.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/retry_ladder.py::_step_category` | The step→category map returned `delivery`, which is not in the Error Store's closed enum, so `advance` on the last pipeline step raised `InvalidErrorCategory` instead of recording a rung. | high | `advance(step="delivery")` with the old map → `InvalidErrorCategory: category 'delivery' not in [...]`; with the fix → `next_rung=2, category='coding'`. Nothing outside tests calls `advance`, so the bug was latent, not user-visible. | **patched**: derive from `get_args(ErrorCategory)`; regression test asserts every `STEP_ORDER` step yields an accepted category. |
| 2 | `harness/regression_set.py::bench_query` | Mixed metric definitions were averaged and mislabelled; the guard the code's own comment claims was absent. | high | Read of the function: `metric_def = rows[0][5]` vs `sum(r[4] for r in rows)/len(rows)`; only `distinct_contracts` was checked. | **patched**: `NonComparableSet` on mixed definitions; 2 tests. |
| 3 | `_ensure_table` in 9 modules | Every one was a hand-copied duplicate of a migration; `run_event_log`'s had already lost an index. | medium | Derived 13 duplicated table definitions programmatically; `idx_run_events_run_id` present in migrate.py, absent from the bootstrap path. | **patched**: `migrate.ensure_tables`; test asserts bootstrapped schema == migrated schema, and was verified to *fail* when the index is simulated away. |
| 4 | `harness/cli.py::run_command` | The ticket's first verify clause (`run --inject-failure-at coding`) named a flag that did not exist, and nothing outside tests called `retry_ladder.advance` — so the ladder had no production caller at all. | noted, then **patched** | `harness run --help` listed only `--project`/`--run-id`; `grep` for `advance(` outside `retry_ladder` found no caller. | **patched**: `--inject-failure-at STEP` records a synthetic failure through the ladder and continues. The flag is the ladder's first production caller, so a regression in it — or in the step→category mapping it depends on — now fails a test instead of surfacing in production. Also removed a 4th copy of `STEP_ORDER` that `run_command` re-listed inline. |

## Design Notes

**Why `ensure_tables` rather than "just run migrations".** The stores keep a
bootstrap path on purpose: tests, `serve --demo`, and any CLI command that opens
a store before the harness boots must not claim a schema version they did not
apply (`run_migrations` records versions in `_migrations` and validates SQL
hashes). `ensure_tables` creates the tables without touching that bookkeeping,
which is the behavior the hand-copied helpers were reaching for.

**Why the migration/DDL work is the highest-value item here.** Two parallel
schema definitions is not a style problem: it means the schema an operator gets
depends on which code path created the table first. The refactor makes the
migrated schema the only schema, and the new test fails the moment anyone
re-introduces a copy.
