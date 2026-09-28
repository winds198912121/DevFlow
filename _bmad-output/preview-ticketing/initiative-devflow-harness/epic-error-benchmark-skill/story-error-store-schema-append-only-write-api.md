---
id: 1
type: story
title: "Error store schema + append-only write API"
parent: epic-error-benchmark-skill
tracker_id: "24"
remote: "https://github.com/winds198912121/DevFlow/issues/24"
covers: [FR-13, FR-14, AD-4, PRD-addendum-§5]
risk: medium
refined: true
---

# Error store schema + append-only write API

## Description

Adds the error_records table to var/harness.sqlite (schema_version=2 migration per Epic 2 story 1's harness.migrate). Implements harness.error_store.append(record) -> record_id with the schema FR-13 / PRD addendum §5: record_id (ULID), project_id, run_id, step, attempt, category, root_cause[], correction[], retry[], result, recorded_at, hash. Records are immutable post-write (FR-14 / AD-4): edit returns error_store_immutable. Indexes on (project_id, run_id, step) and (category) for FR-16.

## Acceptance Criteria

1. **Append returns a ULID and persists the record**
   **Given** an in-memory error record with all required fields filled (record_id omitted, project_id, run_id, step, attempt, category, root_cause, correction, retry, result)
   **When** `harness.error_store.append(record)` is called
   **Then** it returns a record_id (ULID), persists the row in error_records, and the row's `hash` matches `sha256:` of `canonical_bytes(record_with_id)`
2. **Edit returns error_store_immutable**
   **Given** a persisted error record with id=R1
   **When** a subsequent attempt mutates R1 (any column)
   **Then** the call returns `error_store_immutable` and R1 in the database is unchanged
3. **Filtered read is deterministic**
   **Given** 5 error records across projects P1/P2 and steps coding/testing
   **When** a query filter `(project_id=P1, step=coding)` runs
   **Then** the returned list contains only P1+coding records, ordered by recorded_at asc, and is stable across two runs
4. **Closed-list category is enforced at write time**
   **Given** an in-memory record with `category: bogus`
   **When** `harness.error_store.append(record)` is called
   **Then** it returns `invalid_error_category` without persisting a row
5. **Schema migration is idempotent**
   **Given** var/harness.sqlite at schema_version=2 (after Epic 2 story 1's migration)
   **When** Epic 2 story 1's migration runs a second time
   **Then** no rows are altered and the migration log is unchanged
6. **Indexes support NFR-Obs-2 query**
   **Given** the error_records table has indexes on (project_id, run_id, step) and (category)
   **When** a query filters by `category=skill, project_id=P1`
   **Then** it returns in ≤ 100ms on a seeded fixture of 10,000 records

## Boundaries

- Must not change: the error record's JSON wire format (PRD addendum §5 + FR-13 schema are stable). The retry ladder (Epic 3 story 3) consumes `retry[]`; do not rename or reshape the array.
- Must not add: any column that the retry ladder or benchmark query does not need (defer to a follow-on migration if a new field is required).

## References

- parent — _bmad-output/preview-ticketing/initiative-devflow-harness/epic-error-benchmark-skill/epic-error-benchmark-skill.md
- architecture — _bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md#ad-4
- spec — _bmad-output/specs/spec-devflow/failure-modes.md (12 closed categories + retry ladder)
- spec — _bmad-output/specs/spec-devflow/glossary.md (Error record, Error category)
- prd — _bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md, FR-13, FR-14
- prd — _bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/addendum.md, §5 error schema

## Notes

- Decision (2026-09-27): migration version is 2 because Epic 2 story 1's harness.migrate ships schema_version=1 with empty tables; this story adds the error_records table at schema_version=2.
- Decision (2026-09-27): the `hash` field on each record is the sha256 of canonical_bytes(record_with_id), computed via harness.canonical (AD-17 sole sha256 path). Stored on write, not recomputed on read (canonical-bytes is deterministic; recomputation is wasted work).
- Assumption (2026-09-27): the 12-category closed list is fixed at PRD addendum §5 — `requirement | research | design | coding | testing | review | agent | llm | skill | tool | environment | integration`. New categories require a SPEC update.
- Assumption (2026-09-27): `retry[]` is an array of {rung_number, executor_tuple, result, timestamp}; the retry ladder (Epic 3 story 3) owns the schema and validates each entry at append time.
- Open (OQ-7): step ↔ BMAD-skill ownership ratification may add category refinements (e.g. per-BMAD-skill category); out of scope for this story.
