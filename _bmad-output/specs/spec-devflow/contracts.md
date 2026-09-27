# Contracts

Schema source-of-truth files live outside this spec folder; this companion explains what each one binds, what the harness does with it, and what extending it requires.

## Authoritative files

| Contract | Source-of-truth path | Resolves | Locked by |
| --- | --- | --- | --- |
| `test-report.json` v1 | `_bmad-output/contracts/test-report.schema.json` | PRD OQ-2 / D2 | PRD A7 (2026-09-27) |
| Acknowledgement record v1 | `_bmad-output/contracts/acknowledgement-record.schema.json` | PRD D5 / OQ-5 | PRD A8 (2026-09-27) |

Both files are validated Draft 2020-12 JSON Schemas. The harness imports them through `harness/contracts/__init__.py`; any other path is rejected by `tools/check_layer_boundaries.py` (AD-26).

## `test-report.json`

The Testing step's output artifact. Resolves PRD FR-3 (per-step artifact contracts) for the testing row specifically — every other step's contract is owned by its BMAD Skill (see `step-skill-map.md`).

### Top-level fields

| Field | Type | Purpose |
| --- | --- | --- |
| `step` | constant `"testing"` | v1 locks the step this contract applies to. |
| `run_id`, `project_id` | string | Match run-event log (NFR-Obs-1); align with executor tuple + Acknowledgement path triple. |
| `executor_tuple` | `{agent, model, skills[]}` | Same shape as PRD FR-5 + FR-6; enables per-executor-tuple regression set filtering (FR-18). `agent` may be `"human"` for `session` / `trivial` tier runs that still emit a report. |
| `started_at`, `ended_at` | RFC 3339 UTC | Span matched against the run event for NFR-Perf-1 (step-launch overhead) computation. |
| `outcome` | `"pass" \| "fail" \| "error"` | `error` is distinct from `fail`: the executor could not produce a verdict (network / skill crash / cost overrun). |
| `cases[]` | array of `{id, name, acceptance_ref, status, evidence?, duration_ms?}` | One entry per acceptance criterion exercised. `acceptance_ref` references either a PRD FR id (`FR-17`) or a SPEC acceptance id (`AC-NN`); the linkage is what makes acceptance_coverage meaningful. |
| `acceptance_coverage` | `{fr_total, fr_passed}` | FR-pass ratio = `fr_passed / fr_total`. Drives SM-3 error log completeness and bench comparability filters. |

### Versioning rule

PRD A7 pins this schema as the v1 minimum. Extending it (adding optional fields, widening `outcome`, splitting `cases[]` into pass/fail/skipped buckets) is permitted without a schema-version bump IF AND ONLY IF the change is **additive and backward-compatible** (new optional fields, new enum values that older consumers treat as failures). Any breaking change requires a new contract file (`test-report.schema.v2.json`) and a `schema_version` field on the artifact; the harness MUST refuse a v2 artifact with a v1 expectation.

### Validation posture

- The harness validates every `test-report.json` against the schema BEFORE the Gate (FR-9 `pending` state).
- Schema violations are recorded as error records with `category: testing` (PRD error category list).
- `cases[].evidence` is optional but recommended for audit (UJ-3); absence does not fail validation.

## Acknowledgement record

The Gate approval record for every step. Resolves PRD FR-10 / FR-11 / NFR-Sec-2 and PRD D5.

### Top-level fields

| Field | Type | Purpose |
| --- | --- | --- |
| `acknowledger` | string | Human user id (`mei@team`) OR `check:<name>` for automated regressions / benchmark passes. The two are not interchangeable — automated acknowledgements may NOT carry a human-shaped acknowledger. |
| `timestamp` | RFC 3339 UTC | Aligned with the run event (AD-14). |
| `verdict` | `"accepted" \| "accepted-with-open-items" \| "rejected"` | Three-valued (AD-12). `accepted-with-open-items` requires `open_items[]`; `rejected` requires `rejection_reason`. |
| `signature` | string | Ed25519 over the canonical serialization of `{path triple, body}` (AD-23). Algorithm + key id are implementation-detail recorded in `var/secrets/harness.key.pub`. |
| `artifact_ref` | `{step, project_id, run_id, hash: "sha256:..."}` | Back-reference to the locked artifact (FR-11). The hash triple ties this record to a specific artifact version. |
| `open_items[]` | array | Present iff `verdict = accepted-with-open-items`. Each entry: `{id, description, owner?, due?}`. |
| `rejection_reason` | string | Present iff `verdict = rejected`. Surfaced in the error record (FR-13). |

### Storage paths

Two paths are intentionally in use; both are valid v1 stances:

| Stance | Path shape | Source | Pros | Cons |
| --- | --- | --- | --- | --- |
| **Spine (adopted)** | `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` (ULID) | spine AD-5 + AD-23 | ULID gives collision-free enumeration; path triple is in the signature so copy-paste forgery across projects is impossible | Deeper path; tooling must glob recursively |
| **PRD (adopted)** | `acknowledgements/<step>-<artifact-hash-prefix>.json` (flat, 8-char hash prefix) | PRD A8 | Simple to browse; one directory; easy to ship alongside an artifact | No project / run scoping in the path; relies on `artifact_ref` to disambiguate; no path signature coverage |

The spec adopts the spine stance (nested ULID, AD-23 path-triple signature coverage) and notes the PRD-A8 wording as a known naming divergence. Resolution to a single stance is deferred to a future spec update; do not silently migrate between forms.

### Skipped-Gate paths

When the size tier does not enforce a Gate (FR-12: `trivial` always skipped; `session` Research / Coding / Testing / Review / Delivery skipped), NO Acknowledgement record is written. The step-end run event carries `gate_mode: skipped` + an implicit `verdict: accepted` (FR-10, AD-11). A skipped Gate is the only path to a `Locked` step without an Acknowledgement record.

## What extending either schema requires

1. Edit the schema file.
2. Run the jsonschema positive + negative cases (see commit history for `test-report.schema.json` — three cases minimum: a passing sample, a sample rejecting `step: "design"` on the test schema, and a sample rejecting a missing required field).
3. Update this companion's "Versioning rule" section.
4. Append a `(decision)` memlog entry capturing the field added, the rationale, and the downstream consumers notified.
5. If the change affects any PRD FR or NFR, the PRD must be updated in lockstep (this spec cites PRD §9 as the cross-document sync point).

## What this companion deliberately does NOT specify

- The exact JSON wire format for `executor_tuple` hashing — that's AD-10 + AD-17 territory.
- The list of fields in Herdr events — that's FR-29 + spine AD-9 (closed schema, do not extend).
- The error record shape — that's PRD addendum §5 + FR-13.
- The skill-bump-registry record shape — that's AD-6 + PRD FR-22/FR-23.

Each of those has its own owning AD or PRD reference; if you find yourself reaching for them, route to the right document.
