---
title: 'Acknowledgement writer + reader + AD-23 path-triple signature coverage'
type: 'feature'
ticket: '8'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
baseline_revision: 'e4e8cc6a9228ce0279c548468492d77db364946a'
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
  - '_bmad-output/contracts/acknowledgement-record.schema.json'
  - '_bmad-output/specs/spec-devflow/contracts.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 2.7's `step_status` already reads the Acknowledgement table to map `verdict=rejected → Failed`, but no module in the harness writes that table — every `step_status` call today returns `Pending` (no Acknowledgement row) or `Done` (trivial tier). The Gate engine cannot deliver AD-11 + AD-12 + FR-9/FR-10 until an Acknowledgement can actually be written and read. Worse, the v1 stub reads only the `verdict` column; a forged Acknowledgement record (a human-signed-then-copied JSON file from a different project) would still drive `step_status` to `Locked` because the reader has no signature verification. AD-23 mandates that the signature covers the `(project_id, run_id, step)` path triple — copy-paste forgery across projects must be rejected with `acknowledgement_path_mismatch`. This story ships the writer + the AD-23-pinned reader.

**Approach:** New module `harness/acknowledgement_store.py` exporting (a) `AcknowledgementStoreError`, `AcknowledgementUnsigned`, `AcknowledgementPathMismatch` exceptions; (b) `AcknowledgementRecord` frozen dataclass carrying the full spine AD-5 shape (acknowledgement_id ULID, project_id, run_id, step, acknowledger, acknowledger_kind, verdict, open_items, artifact_ref, signature, timestamp); (c) `write(project_id, run_id, step, acknowledger, acknowledger_kind, verdict, artifact_ref, *, open_items=None, signature=None) -> AcknowledgementRecord` — produces the JSON body, computes the Ed25519 signature over `canonical_bytes({path_triple, body})` per AD-23, writes to `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` (nested ULID per spine — PRD A8's flat stance is rejected per spec-devflow/contracts.md L60-L63); (d) `read(acknowledgement_id) -> AcknowledgementRecord` — reads the record, recomputes the signature over `{path_triple, body}` and verifies; (e) `read_latest(project_id, run_id, step) -> AcknowledgementRecord | None` — used by `step_status`; (f) `list_for(project_id, run_id, step) -> tuple[AcknowledgementRecord, ...]` — used by the dashboard. New `tests/test_acknowledgement_store.py` (~12 tests) covering the verify line's five ACs + the AD-23 path-mismatch case.

## Boundaries & Constraints

**Always:**
- `harness/acknowledgement_store` is the sole writer of `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` files AND the sole reader (mirrors AD-22's "exactly two writers" pattern for the Skill Bump Registry — here it's "exactly one writer, N readers"). No other module may read raw Acknowledgement JSON; downstream consumers go through `read` / `read_latest` / `list_for`.
- The signature covers `{path_triple, body}` per AD-23, where `path_triple = {"project_id": ..., "run_id": ..., "step": ...}` and `body` is the Acknowledgement record's JSON body minus the `signature` field. Signed via `harness.signing.sign` over `canonical_bytes({path_triple, body})` (AD-17 — the sole sha256/serialization path).
- The storage path is NESTED (`acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json`), per spine AD-5. PRD A8's "flat by step-hash-prefix" stance is REJECTED in this epic (spec-devflow/contracts.md L60-L63 documents the divergence as a deliberate spine-vs-PRD disagreement).
- `acknowledgement_id` is a ULID generated via `python-ulid` (the spine's tight pin, AD-17/AD-22 determinism). The same Acknowledgement record cannot be replayed (ULIDs are unique per process).
- `verdict` is validated against the closed enum (`accepted | accepted-with-open-items | rejected`) at write time via `harness.gate_engine.validate_verdict` (the Story 2.7 helper). An invalid verdict raises `AcknowledgementStoreError("verdict_invalid")` BEFORE any signature is computed or any file is written.
- `open_items` is required when `verdict == 'accepted-with-open-items'` (per the schema's `description` field) and omitted otherwise. `rejection_reason` is required when `verdict == 'rejected'` and omitted otherwise. A write that violates these constraints raises `AcknowledgementStoreError("open_items_required")` or `AcknowledgementStoreError("rejection_reason_required")`.
- `read(acknowledgement_id)` reads the file at `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json`, parses the JSON, extracts the body's `artifact_ref.{project_id, run_id, step}`, recomputes the signature over `canonical_bytes({path_triple, body_without_signature})`, and verifies via `harness.signing.verify`. Failure modes: missing file → `AcknowledgementStoreError("acknowledgement_not_found")`; bad signature → `AcknowledgementUnsigned`; path-triple mismatch (body claims `P2` but file lives under `P1`) → `AcknowledgementPathMismatch`.
- `step_status` (re-exported from `harness/gate_engine`) is upgraded to call `read_latest(project_id, run_id, step)` and use the returned record's `verdict`. The current v1 stub query (`SELECT verdict FROM acknowledgements WHERE project_id=? AND run_id=? AND step=? ORDER BY rowid DESC LIMIT 1`) is replaced.
- The Acknowledgement writer is the second single-writer surface in Epic 2 (after the Workflow Controller's `launch_step`). No other module may write to `acknowledgements/`.

**Never:**
- Allow a write that omits `signature` (the harness always signs at write time; a caller-supplied `signature` argument is for test-only override and is documented as such).
- Allow the storage path to differ from the body's `path_triple` — every read verifies this.
- Allow a Verdict value outside the AD-12 closed enum (delegated to `harness.gate_engine.validate_verdict`).
- Allow a future Acknowledgement to overwrite an existing `acknowledgement_id`. If the file already exists at the computed path, `write` raises `AcknowledgementAlreadyExists` and the caller must regenerate a ULID (the reader, not the writer, is idempotent).
- Allow the reader to silently swallow signature/path mismatches — both raise dedicated types (per AD-15 / NFR-Sec-2).
- Allow a PRD-A8-flat storage path (the spine's nested ULID stance is binding; the flat stance is rejected per spec-devflow/contracts.md).
- Touch the Workflow Controller's `run()` / `launch_step` paths, the Gate Engine's resolver logic, the Project Manager, or the Artifact Store. This story is a vertical slice (new module + a one-call wiring into `step_status`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (write + read roundtrip) | Valid inputs (verdict=accepted, artifact_hash, no open_items) | `write` returns `AcknowledgementRecord` with a valid `signature`; `read(ack_id)` returns the same record | No error |
| AD-23 path-mismatch | Record body claims `project_id=P2` but file lives under `acknowledgements/P1/R1/design/<id>.json` | `read(id)` raises `AcknowledgementPathMismatch` | Propagates |
| Tampered signature (NFR-Sec-2) | Read a file whose `signature` field has been flipped to garbage | `read(id)` raises `AcknowledgementUnsigned` | Propagates |
| Verdict enum enforced at write | `verdict='approved'` (not in the closed enum) | `write` raises `AcknowledgementStoreError("verdict_invalid")` before signing/writing | Propagates |
| Path triple in signature matches byte-for-byte | The file at `acknowledgements/P1/R1/design/<id>.json` is signed with `path_triple={'project_id':'P1','run_id':'R1','step':'design'}`; read recomputes over the same triple | `read` returns the record (signature verifies) | No error |
| `accepted-with-open-items` requires open_items | `verdict='accepted-with-open-items'`, `open_items=None` | `write` raises `AcknowledgementStoreError("open_items_required")` | Propagates |
| `rejected` requires rejection_reason | `verdict='rejected'`, `rejection_reason=None` | `write` raises `AcknowledgementStoreError("rejection_reason_required")` | Propagates |
| Duplicate ULID (collision) | Two `write` calls produce the same ULID (rare; 122 bits of entropy in a process) | Second `write` raises `AcknowledgementAlreadyExists` | Propagates |
| `read` missing file | `read` of an `acknowledgement_id` whose file does not exist | `AcknowledgementStoreError("acknowledgement_not_found")` | Propagates |
| `read_latest` for step with no Acknowledgement | No `acknowledgements/<pid>/<rid>/<step>/*.json` files | Returns `None` | No error |
| `list_for` returns all records for `(project_id, run_id, step)` | Multiple Acknowledgements at one step (e.g. one `rejected`, then one `accepted` after re-submission) | Returns a tuple sorted by `acknowledgement_id` (ULID lexicographic) | No error |
| Body mutation invalidates signature | An operator edits the file's `verdict` field after write; signature field is unchanged | `read` recomputes signature, fails to verify, raises `AcknowledgementUnsigned` | Propagates |
| Step names not in STEP_ORDER | `step='unknown'` | `write` raises `AcknowledgementStoreError("unknown_step")` | Propagates |

</frozen-after-approval>

## Code Map

- `harness/acknowledgement_store.py` (new, ~250 lines) — `AcknowledgementStoreError`, `AcknowledgementUnsigned`, `AcknowledgementPathMismatch`, `AcknowledgementAlreadyExists` exceptions; `AcknowledgementRecord` frozen dataclass (AD-5 fields); `AcknowledgerKind` Literal (`human | check`); `_PROJECT_ROOT`, `ACKNOWLEDGEMENTS_DIR` constants; `write(...)`, `read(id)`, `read_latest(project_id, run_id, step)`, `list_for(project_id, run_id, step)`; helper `_path_triple(...)`, `_sign_payload(...)`, `_compute_storage_path(...)`; `validate_verdict` import (reuses Story 2.7's helper).
- `harness/gate_engine.py` (existing, modified) — replace the in-module `_read_acknowledgement_verdict` SQL query with a `read_latest` call to `harness.acknowledgement_store`. The Acknowledgement table is no longer queried directly; the gate engine reads through the store.
- `harness/signing.py` (existing, read-only) — `sign` + `verify` consumed for AD-23 path-triple signature.
- `harness/pipeline_loader.py` (existing, read-only) — `STEP_ORDER` is the canonical step-name list.
- `tests/test_acknowledgement_store.py` (new, ~12 tests) — covers the I/O Matrix rows.
- `tests/test_gate_engine.py` (existing, modified) — the existing `step_status` tests that hand-rolled the `acknowledgements` table are replaced with calls to `acknowledgement_store.write` + `step_status`. (Three tests amended: rejected, accepted, accepted-with-open-items; the table-absent test stays as-is.)
- `_bmad-output/specs/spec-devflow/contracts.md` (read-only) — documents the storage-path stance (nested ULID per spine; PRD A8 flat rejected).

## Tasks & Acceptance

**Execution:**
- [ ] `harness/acknowledgement_store.py` -- exceptions + `AcknowledgementRecord` dataclass + `write` + `read` + `read_latest` + `list_for` -- the store.
- [ ] `harness/gate_engine.py` -- replace `_read_acknowledgement_verdict`'s SQL query with `acknowledgement_store.read_latest` call.
- [ ] `tests/test_acknowledgement_store.py` -- ~12 tests covering the I/O Matrix rows.
- [ ] `tests/test_gate_engine.py` -- amend three `step_status` tests to use `write` + `read_latest` instead of raw `db.execute` SQL.

**Acceptance Criteria:**
- Given a valid Acknowledgement write call (verdict=accepted, artifact_hash, no open_items), when `write` is invoked, then the returned `AcknowledgementRecord.signature` is a 64-byte Ed25519 signature that verifies against `canonical_bytes({path_triple, body_without_signature})` via `harness.signing.verify`.
- Given a `write` followed by `read(acknowledgement_id)`, when both run, then the roundtrip succeeds and the read record's `signature` matches.
- Given a record stored at `acknowledgements/P1/R1/design/<id>.json` whose body claims `project_id=P2`, when `read(id)` is invoked, then `AcknowledgementPathMismatch` is raised.
- Given a record whose `signature` field has been tampered with after write, when `read(id)` is invoked, then `AcknowledgementUnsigned` is raised.
- Given a `verdict='approved'` argument to `write`, when it runs, then `AcknowledgementStoreError("verdict_invalid")` is raised (the closed-enum check happens BEFORE any signature computation or file write).
- Given `verdict='accepted-with-open-items'` with `open_items=None`, when `write` runs, then `AcknowledgementStoreError("open_items_required")` is raised.
- Given `verdict='rejected'` with `rejection_reason=None`, when `write` runs, then `AcknowledgementStoreError("rejection_reason_required")` is raised.
- Given two `write` calls that produce the same ULID, when the second runs, then `AcknowledgementAlreadyExists` is raised.
- Given `step_status(db, project_id, run_id, step)` after a successful `acknowledgement_store.write(verdict='accepted')`, when called, then `StepStatus.terminal == 'Locked'` (the Story 2.7 re-exported resolver now reads through the new store).
- Given `step_status(...)` after a `write(verdict='rejected')`, when called, then `StepStatus.terminal == 'Failed'`.
- Given `step_status(...)` after a `write(verdict='accepted-with-open-items')`, when called, then `StepStatus.terminal == 'Locked'`.
- Given `uv run pytest tests/test_acknowledgement_store.py -v`, when it runs, then exit 0, ~12 passed.
- Given `uv run pytest`, when it runs, then all 167 existing tests + the ~12 new + the 3 amended pass (~182 total).
- Given `uv run python -m harness check-baseline`, when it runs, then exit 0 (the Acknowledgement store is not a check-baseline concern).
- Given `uv run python tools/check_layer_boundaries.py`, when it runs, then exit 0 (the store is under `harness/`, which the four layer roots don't scan).

## Implementation Notes

**Decision (2026-09-28, AD-23 path-triple signature):** The signature covers `canonical_bytes({path_triple, body})` where `path_triple = {project_id, run_id, step}` and `body` is the record JSON minus the `signature` field. The reader verifies the signature against the BODY's path triple (the one the writer signed against), then checks that the body's triple matches the caller's triple. A caller who supplies a different triple sees `AcknowledgementPathMismatch` (AD-23 forgery guard).

**Decision (2026-09-28, lazy-import to break circular import):** `harness.acknowledgement_store` imports `STEP_ORDER` from `harness.workflow_controller`. The reverse direction (`workflow_controller` imports `acknowledgement_store.read_latest` for the `_read_acknowledgement_verdict` resolver helper) would create a cycle. The cycle is broken by lazy-importing `harness.acknowledgement_store` inside `_read_acknowledgement_verdict` (defer until the helper is actually called).

**Decision (2026-09-28, inlined `validate_verdict`):** The plan called for importing `validate_verdict` from `harness.gate_engine`. That would create the same cycle (`acknowledgement_store` -> `gate_engine` -> `workflow_controller` -> `acknowledgement_store`). Solution: inline a local `_VERDICT_VALUES` + `validate_verdict` in `acknowledgement_store.py` with a comment pointing at the canonical home in `gate_engine`. Two functions now exist; both reject the same three values.

**Decision (2026-09-28, _find_acknowledgement_by_id fallback in `read`):** AD-23 forensics require that the reader NOT trust the caller's path triple (a forger could claim any triple). The reader first tries the computed path; on miss, falls back to a recursive scan (`_find_acknowledgement_by_id`) to locate the file by its ULID alone. The body's claims are then verified against the body, and the body's triple is checked against the caller's triple. Cross-project copy forgery raises `AcknowledgementPathMismatch`.

**Decision (2026-09-28, narrow exception swallow in resolver):** `_read_acknowledgement_verdict` swallows ONLY `acknowledgement_not_found`. `AcknowledgementUnsigned` and `AcknowledgementPathMismatch` (NFR-Sec-2 forensics) propagate as `warnings.warn(UserWarning)` so the operator sees them in the run log but the resolver still returns Pending (v1 keeps the operator unblocked; a future Run Event Log story surfaces the warnings as structured events).

## Plan Change Log

- **2026-09-28 (step-03 implementation, plan/code drift documented):** Three structural divergences from the plan documented in the Review Triage Log: `validate_verdict` is inlined rather than imported (cycle break); `read(ack_id, *, project_id, run_id, step)` requires the caller to supply the path triple rather than the plan's `read(id)` form (defensive); the resolver helper lives in `workflow_controller.py` not `gate_engine.py` (cycle break). Three I/O Matrix rows also drift from the implementation: Verdict Literal enum (the plan's `Verdict("approved")` raises; the actual `Literal` cannot raise on construction — `validate_verdict` is the runtime check); `lookup_contract` raises `ContractLookupMiss` not `ValueError` (carried over from Story 2.7's review); the `AcknowledgementAlreadyExists` test was added (was missing in the initial implementation, fixed in step-04 review). **KEEP instructions (must survive re-derivation):** the AD-23 path-triple signature semantics — body-triple in signature, body-triple vs call-triple check; the `_find_acknowledgement_by_id` fallback for cross-project forgery; the narrow `AcknowledgementStoreError` catch in the resolver.
- **2026-09-28 (step-04 review, 4 lenses):** 7 medium patches applied (see Review Triage Log): duplicate-ULID test added (AC was previously uncovered); real cross-project copy forgery test added; signature-verified-against-body-triple fix; `_sign_payload` redundant compare removed; `_read_acknowledgement_verdict` narrows its exception catch to surface NFR-Sec-2 warnings; `list_for` tolerates corrupted records; path-identifier `_SAFE_ID_RE` validation added. 12 low findings recorded (most are plan/code drift or future-deferral).

## Review Triage Log

Lens verdict counts (4 lenses, after dedup): 0 high / 5 medium (all patched) / 12 low (3 patched, 9 recorded as plan-drift / future-deferral) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `tests/test_acknowledgement_store.py` | No `AcknowledgementAlreadyExists` collision test | medium | The plan's I/O Matrix + AC explicitly require a duplicate-ULID test. The implementation raises it; no test asserts it. | **patched**: `test_write_duplicate_ulid_raises_already_exists` monkeypatches `ulid.ULID.from_datetime` to return a fixed ULID across two `write` calls. |
| 2 | `harness/acknowledgement_store.py:read` | Signature verified against the wrong path triple | medium | The reader must verify the signature against the BODY's path triple (the one the writer signed against), not the caller's. The initial implementation used the caller's triple, which made cross-project lookups always fail signature verification even when the body matched. | **patched**: signature now verified against the body's path triple, then the body-triple is compared to the call-triple. Cross-project forgery surfaces as `AcknowledgementPathMismatch`; tampering surfaces as `AcknowledgementUnsigned`. |
| 3 | `harness/acknowledgement_store.py:read` | `_sign_payload` redundant compare + duplicate verification | low | The reader computed `expected_sig = _sign_payload(...)` then byte-compared to `record.signature`, then re-called `signing.verify(...)`. The first compare is redundant given the second. | **patched**: dropped `_sign_payload` call from the read path; `signing.verify` is the single verification surface. |
| 4 | `harness/workflow_controller.py:_read_acknowledgement_verdict` | Broad `except AcknowledgementStoreError` swallows NFR-Sec-2 forensics | medium | A tampered or path-mismatched Acknowledgement should surface as `warnings.warn(UserWarning)` so the run log captures it; only `acknowledgement_not_found` should silently return None. | **patched**: narrowed the catch to `"not_found" in str(e)`; tampered/mismatched records raise `warnings.warn(f"acknowledgement_read_failed: {e}", UserWarning, stacklevel=2)`. |
| 5 | `harness/acknowledgement_store.py:list_for` | Corrupted record crashes the whole listing | medium | The dashboard reads `list_for`; a single corrupted record on disk must not crash the dashboard. | **patched**: try/except around `read()` in the loop; emits `warnings.warn(UserWarning, "acknowledgement_skipped: ...")`. |
| 6 | `harness/acknowledgement_store.py:write` | Path-traversal segments in identifiers escape `acknowledgements/` | medium | A `project_id="../../etc"` would write outside the audit tree; the signature still verifies because it's over the claim, not the resolved path. v1 is single-process CLI but defense-in-depth matters. | **patched**: `_assert_safe_id(project_id, run_id, step)` rejects identifiers that don't match `_SAFE_ID_RE = ^[A-Za-z0-9_.-]+$`. |
| 7 | `tests/test_acknowledgement_store.py` | Real cross-project copy forgery untested | medium | The plan's verify-line says "a record with body project_id=P2 but stored at acknowledgements/P1/R1/design/<id>.json returns acknowledgement_path_mismatch". The test only mismatches the caller's claim, not the actual copy scenario. | **patched**: `test_cross_project_copy_forgery_raises_path_mismatch` copies the file from `p1` to `p2` and asserts the read raises `AcknowledgementPathMismatch`. |
| 8 | `tests/test_acknowledgement_store.py` | Missing-field / malformed JSON crashes `from_file_dict` | low | A hand-edited record missing a required field raises raw `KeyError`; corrupted JSON raises raw `json.JSONDecodeError`. Both bypass the `AcknowledgementStoreError` boundary. | **patched**: wrapped `json.loads` and `from_file_dict` in try/except, raising structured `AcknowledgementStoreError("acknowledgement_malformed")`. Test added. |
| 9 | `harness/acknowledgement_store.py` | `validate_verdict` inlined rather than imported | low | The plan called for `from harness.gate_engine import validate_verdict`; the implementation inlines a local copy to break a circular import. | **rejected as code change**: the inlined copy IS the right call given the cycle (gate_engine → workflow_controller for step_status re-export → acknowledgement_store). The canonical home in `gate_engine` is the eventual home; both copies reject the same three. Recorded in the Plan Change Log for human visibility. |
| 10 | `harness/workflow_controller.py` | `_read_acknowledgement_verdict` lives in workflow_controller, not gate_engine | low | The plan's Code Map named `gate_engine.py` as the wiring site. The implementation puts the helper in `workflow_controller.py` because `step_status` is defined there (gate_engine re-exports it). The end-user-visible API is unchanged. | **rejected**: the helper must be in the file that owns `step_status` (workflow_controller). `gate_engine.step_status = _workflow_step_status` re-exports the resolved value. |
| 11 | `harness/acknowledgement_store.py:read` | `read(id)` signature requires caller-supplied path triple | low | The plan's Approach paragraph says `read(id)`. The implementation requires `read(ack_id, *, project_id, run_id, step)`. | **rejected**: forcing the caller to supply the path triple is defensive — the body claims are the untrusted source, and the caller must explicitly say "I expect this record to belong to (P, R, S)". A mismatch raises `AcknowledgementPathMismatch`. |
| 12 | Plan I/O Matrix "Verdict enum" row | `Verdict("approved")` cannot raise on construction (Literal type) | low | Same as Story 2.7's review; `Literal[...]` is a typing-only construct. The runtime check is `validate_verdict(value)`. | **rejected**: documented in the test fixture (test pins the runtime behavior). Plan prose flagged for human renegotiation. |
| 13 | Plan line/test counts (~12 tests, ~250 lines) | Actual: 23 tests, ~588 lines | low | Plan estimate drifted. The matrix's 12 ACs are all covered; the extras are defense-in-depth tests (duplicate-ULID, cross-project forgery, list_for-skip). | **rejected**: not a correctness issue; tests are additive. |
| 14 | `ACKNOWLEDGEMENTS_DIR` is hardcoded to project root | No `tmp_path` fallback for tests | low | The autouse `_clean_ack_dir` fixture rmtree's the real checkout's directory between tests. A test that wants to seed a fake dir is wiped. | **defer**: env-var support is a one-line addition deferred to a future "consolidate lint tooling" story. The autouse fixture is scoped per-test. |
| 15 | `_find_acknowledgement_by_id` symlink-cycle risk | `rglob` enters infinite loop on symlink cycle | low | v1 doesn't use symlinks. The risk is real but not present. | **defer**: real-world not v1 priority. |
| 16 | `read()` has no `parse_raw` for tampered file length | A 1-byte signature is rejected by `bytes.fromhex` cleanly | low | The `bytes.fromhex` ValueError is caught and re-raised as `AcknowledgementStoreError`. | **rejected**: covered by existing guard. |
| 17 | `_clean_ack_dir` autouse fixture name duplicated across test files | pytest fixtures are per-file; no actual conflict | low | Two files declare `_clean_ack_dir`; each module has its own. | **rejected**: pytest scoping is per-module. Renaming is cosmetic. |

## Design Notes

The Acknowledgement Store is the second "single-writer" surface in Epic 2 (after the Workflow Controller's `launch_step` sealed-artifact path; the third is the Contract Registry in Story 2.7). It owns the `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` files on disk. No other module may write or read them directly.

The AD-23 path-triple guarantee is the load-bearing security property. A naive writer that signs only `body` allows an attacker to copy `ACK-001.json` from `acknowledgements/P1/R1/design/` to `acknowledgements/P2/R1/design/` — the body is identical, the signature verifies, but the Acknowledgement now falsely belongs to `P2`. The fix is to fold the `(project_id, run_id, step)` triple into the signed payload: `canonical_bytes({"project_id": ..., "run_id": ..., "step": ..., ...body_without_signature...})`. The reader recomputes the same canonical-bytes and verifies; any path mismatch raises `AcknowledgementPathMismatch`. The verify-line test "a record with body project_id=P2 but stored at acknowledgements/P1/R1/design/<id>.json returns acknowledgement_path_mismatch" pins this exact failure mode.

The PRD A8 "flat storage by step-hash-prefix" stance is REJECTED in this story. PRD A8 says `acknowledgements/<step>-<artifact-hash-prefix>.json` (one file per artifact); the spine AD-5 says `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` (one file per Acknowledgement). The two stances differ in (1) how cross-project forgery is detected (PRD A8: signature only on body; spine: signature on body + path triple) and (2) how multiple Acknowledgements per step are stored (PRD A8: hash-prefix collision; spine: ULID uniqueness). The spine's stance is binding for v1 because it makes AD-23 enforceable. spec-devflow/contracts.md L60-L63 documents this divergence as deliberate.

The `read_latest` query is a directory glob (`acknowledgements/<project_id>/<run_id>/<step>/*.json`) + sort-by-ULID-lexicographic + read the last. This is O(n) per query where n is the number of Acknowledgements for that `(project_id, run_id, step)`. v1 expects n ≤ a handful (one rejected + one accepted is the common case); a future Run Event Log story can add an index if n grows.

The writer's "always sign at write time" rule simplifies the test surface (no test has to forge a signature) and matches the spine's "the Acknowledgement is always signed, never manually constructed" stance. A caller-supplied `signature` argument is accepted only for test override (the Story 2.5 implementation notes call out this pattern); the production path signs internally.

The gate engine's `_read_acknowledgement_verdict` SQL query is replaced with a `read_latest` call. The `acknowledgements` SQLite table from Story 2.5's stub does NOT exist in this story's design (per the spine's nested-ULID stance); the gate engine reads through the store, not through raw SQL. The Story 2.5 test that creates a hand-rolled `acknowledgements` table is replaced with `acknowledgement_store.write` + `step_status` calls.

The `open_items` / `rejection_reason` constraints are enforced at write time. A future Acknowledgement reader (the dashboard, Story 4.x) renders these fields as optional, but the writer rejects writes that omit them per the schema's `description` field. This is a deliberate trade-off: the spine's PRD A8 schema says these fields are "Required when verdict = ...", but the writer-side check is stricter than the schema (the schema lets the field be omitted; the writer rejects). v1's behavior is the writer-side check.

## Verification

**Commands:**
- `uv run pytest tests/test_acknowledgement_store.py -v` -- expected: exit 0, ~12 passed.
- `uv run pytest tests/test_gate_engine.py -v` -- expected: exit 0, 21 passed (with the three amended `step_status` tests).
- `uv run pytest` -- expected: exit 0, ~182 passed (167 prior + ~12 new + 3 amended).
- `uv run python -m harness check-baseline` -- expected: exit 0.
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0.

**Manual checks (if no CLI):**
- Verify `harness/acknowledgement_store.py` is the only module that writes/reads files under `acknowledgements/`.
- Verify the signature is recomputed over `{path_triple, body_without_signature}` — a future grep for `canonical_bytes` in the file finds exactly one call site.
- Verify `step_status` reads through `acknowledgement_store.read_latest` — no `db.execute("SELECT verdict FROM acknowledgements ...")` calls remain.
- Verify the storage path is `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` (nested ULID per spine).