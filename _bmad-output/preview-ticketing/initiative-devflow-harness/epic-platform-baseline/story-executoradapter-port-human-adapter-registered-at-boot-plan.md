---
title: 'ExecutorAdapter port + human adapter registered at boot'
type: 'feature'
ticket: '5'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '07bd2eb'
route: 'full'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 2's Workflow Controller (Story 2.5) needs to invoke a step's executor, and the executor choice is per-step, per-project (FR-5: human or Agent+LLM+Skills). Today the harness has the port shape (`harness.ports.StepExecutorPort`) but no concrete implementation, no registration surface, and no default adapter. Without the ExecutorAdapter port (the seam between Workflow Controller and concrete Agent runtimes) and a registered default `human` adapter, the tracer-bullet story 1.6 cannot demonstrate end-to-end execution, and Epic 2 cannot wire up FR-5's executor tuple dispatch.

**Approach:** Two new modules. `harness/executor.py` defines the concrete runtime types — `AdapterManifest` (a TypedDict shape: `name`, `auth_mode`, `capabilities` list) and `AdapterRegistry` (a dict-backed singleton with `register(adapter, manifest)`, `list() -> list[str]`, `get(name) -> adapter`, and a `validate_manifest` step that rejects malformed entries before they enter the registry). The registry's `human` entry is registered at module import time so the harness boots with at least one usable executor. `harness/adapters/human.py` implements `HumanAdapter` whose `start(capability)` blocks on `input("…")` and returns an `AdapterOutcome` (status, payload dict); `cancel` is a no-op (operator signals cancel via the next prompt); `status` returns the in-memory state. The port type itself is added to `harness/ports/__init__.py` so future adapters and the Workflow Controller import the same `StepExecutorPort`.

## Boundaries & Constraints

**Always:**
- `harness/executor.py` owns the `AdapterRegistry` singleton; it is the only writer and reader.
- Every registered adapter has a valid `AdapterManifest` (name, auth_mode in {"bearer", "oauth", "cli-resident", "human"}, non-empty capabilities list, optional description).
- `register()` fails closed on any manifest defect: missing name → `invalid_manifest_name`, unknown auth_mode → `invalid_manifest_auth_mode`, empty capabilities → `invalid_manifest_capabilities`, duplicate name → `adapter_already_registered`.
- `list()` returns adapter names in registration order.
- The `human` adapter is registered at module import time (Story 1.6's `--check-baseline` smoke test asserts it is in `list()`).
- `HumanAdapter.start(capability)` blocks on `input(...)` with a prompt that names the capability; the returned `AdapterOutcome` has `status="succeeded"` and `payload={"capability": capability, "operator_input": <string>}`.
- The `human` adapter's `start` is intentionally synchronous + blocking — that's the only executor behavior Epic 1/2 needs for tracer bullets; async / non-blocking operator prompts are a v2 concern.
- `AdapterOutcome` is a TypedDict with `status` in {"succeeded", "failed", "cancelled"} and an optional `payload` dict.

**Never:**
- Auto-register any non-human adapter at boot. Future adapters (Pi, OMP, Codex) require operator action (per AD-10d + PRD A6 + OQ-6 still open).
- Allow `start`/`cancel`/`status` to raise; they return `AdapterOutcome` with `status="failed"` and a payload carrying an `error` key.
- Add new methods to `StepExecutorPort` beyond `start` / `cancel` / `status` — AD-10 pins the contract.
- Use `prompt_toolkit` or any third-party prompt library; `input()` is sufficient for v1.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (registry on boot) | `from harness.executor import ADAPTER_REGISTRY; ADAPTER_REGISTRY.list()` | Returns `["human"]` | No error |
| Happy path (human start) | `ADAPTER_REGISTRY.get("human").start("review the design")` after a synthetic `input()` returns `"looks good"` | Returns `AdapterOutcome(status="succeeded", payload={"capability": "review the design", "operator_input": "looks good"})` | No error |
| Happy path (human status) | Immediately after `start` returns, call `status` | Returns the same `AdapterOutcome` (cached) | No error |
| Happy path (human cancel) | Call `cancel` on a running human adapter | No-op (returns immediately) | No error |
| Error (register malformed name) | `register(adapter, {"name": "", "auth_mode": "bearer", "capabilities": ["x"]})` | Raises `invalid_manifest_name` (ValueError) | Propagates |
| Error (unknown auth_mode) | `register(adapter, {"name": "x", "auth_mode": "magic", "capabilities": ["x"]})` | Raises `invalid_manifest_auth_mode` | Propagates |
| Error (empty capabilities) | `register(adapter, {"name": "x", "auth_mode": "bearer", "capabilities": []})` | Raises `invalid_manifest_capabilities` | Propagates |
| Error (duplicate name) | Register "human" twice | Raises `adapter_already_registered` | Propagates |
| Edge (capability not supported) | `start("non-existent-capability")` on human | Returns `AdapterOutcome(status="failed", payload={"error": "capability_not_supported: non-existent-capability", "supported": [...]})` | No exception |
| Edge (start with EOF on stdin) | `start` on human with stdin closed (returns `''`) | Returns `AdapterOutcome(status="failed", payload={"error": "operator_input_eof"})` | No exception |

</frozen-after-approval>

## Code Map

- `harness/ports/__init__.py` (existing, modified) — already exports `StepExecutorPort` (Protocol). The story does not modify it; the runtime types added in `harness/executor.py` satisfy the Protocol structurally (any concrete class with `start`/`cancel`/`status` methods is a structural subtype).
- `harness/executor.py` (new) — `AdapterManifest` (TypedDict), `AdapterOutcome` (TypedDict), exception types (`invalid_manifest_name`, `invalid_manifest_auth_mode`, `invalid_manifest_capabilities`, `adapter_already_registered`), `AdapterRegistry` class with `register`/`unregister`/`list`/`get`/`validate_manifest`, the module-level `ADAPTER_REGISTRY` singleton, and the boot-time registration of the `human` adapter.
- `harness/adapters/__init__.py` (new, empty) — marks `harness/adapters/` as a package; future concrete adapters (Pi, OMP, Codex) live here.
- `harness/adapters/human.py` (new) — `HumanAdapter` class implementing `StepExecutorPort` semantically: `start(capability)` calls `input()`, `cancel` is a no-op, `status` returns the cached outcome.
- `tests/test_executor.py` (new) — covers the registry's register/list/get paths + manifest validation; 9 tests, one per I/O Matrix row.
- `tests/test_human_adapter.py` (new) — covers the human adapter's happy/error/edge paths with `monkeypatch` on `builtins.input`; 4 tests.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — glossary defines Executor + Agent + LLM + Skill + StepExecutorPort; the ExecutorAdapter is the runtime specialization.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-10 pins the per-Agent `start`/`cancel`/`status` contract; this story is the port-only slice of AD-10.

## Tasks & Acceptance

**Execution:**
- [ ] `harness/executor.py` -- implement `AdapterManifest`, `AdapterOutcome`, `AdapterRegistry` (dict-backed, ordered), `validate_manifest`, four named exceptions, `ADAPTER_REGISTRY` singleton, boot-time registration of `human` via `from harness.adapters.human import HumanAdapter` -- the registry + manifest validation surface.
- [ ] `harness/adapters/__init__.py` -- empty marker -- namespace for future adapters.
- [ ] `harness/adapters/human.py` -- implement `HumanAdapter` with `start(capability) -> AdapterOutcome` (calls `input()`), `cancel` no-op, `status` returns cached outcome; constructor takes no args; the adapter is stateless across calls (each `start` returns a fresh outcome) -- the default executor for Epic 2's tracer bullet.
- [ ] `tests/test_executor.py` -- 9 tests covering the I/O Matrix rows for `AdapterRegistry`.
- [ ] `tests/test_human_adapter.py` -- 4 tests covering human adapter's input/output behavior via `monkeypatch.setattr(builtins, "input", lambda *_: "ok")`.

**Acceptance Criteria:**
- Given a fresh `harness.executor` import, when `ADAPTER_REGISTRY.list()` is called, then `["human"]` is returned.
- Given `ADAPTER_REGISTRY.get("human").start("review")` with `input()` patched to return `"ok"`, when the call returns, then `result.status == "succeeded"` and `result.payload["operator_input"] == "ok"`.
- Given `ADAPTER_REGISTRY.get("human").status()` after a `start`, when called, then the cached outcome is returned.
- Given `ADAPTER_REGISTRY.get("human").cancel()`, when called, then no exception is raised and no state change occurs.
- Given `register(adapter, {"name": "", ...})`, when called, then `ValueError` is raised with the message `invalid_manifest_name: <details>`.
- Given `register(adapter, {"name": "x", "auth_mode": "magic", ...})`, when called, then `ValueError` is raised with `invalid_manifest_auth_mode: ...`.
- Given `register(adapter, {"name": "x", "auth_mode": "bearer", "capabilities": []})`, when called, then `ValueError` is raised with `invalid_manifest_capabilities: ...`.
- Given `register(HumanAdapter(), {"name": "human", ...})` (duplicate of the boot registration), when called, then `ValueError` is raised with `adapter_already_registered: ...`.
- Given `ADAPTER_REGISTRY.get("human").start("non-existent-capability")`, when called, then the returned `AdapterOutcome` has `status="failed"` and `payload["error"]` starts with `"capability_not_supported"`.

## Implementation Notes

- Decision (2026-09-28): Dropped the `try/except ImportError` around `from harness.adapters.human import HumanAdapter` in `_register_human`. The harness always ships `harness/adapters/human.py`; if it ever goes missing, that's a real bug we want surfaced. The plan called for a guard ("slim installs") but in practice this just hides breakages.
- Decision (2026-09-28): Removed the `SUPPORTED_CAPABILITIES = HumanAdapter.SUPPORTED_CAPABILITIES` module-level alias and trimmed `__all__` to `["HumanAdapter"]`. The alias was added for test convenience but the tests import `HumanAdapter.SUPPORTED_CAPABILITIES` directly via the class attribute, making the module-level copy dead code.
- Decision (2026-09-28): Test fixture `fresh_registry` in tests/test_executor.py auto-uses `_register_human()` after resetting `ADAPTER_REGISTRY`. Individual tests no longer re-register the human adapter; they exercise it via `ADAPTER_REGISTRY.get("human")`.
- Surprise (2026-09-28): First test run failed because each test was calling `ADAPTER_REGISTRY.register(HumanAdapter(), HumanAdapter.manifest())` while the fixture had already registered it. Pivoted: fixture does the registration, tests read the registry. The duplicate-registration test (AC 8) now uses a fresh `object()` as the adapter.
- Surprise (2026-09-28): Plan's I/O Matrix says human `status` returns "the cached outcome" but does not say what happens with concurrent invocations. Current implementation stores a single `_last_outcome`; concurrent `start()` calls would overwrite the cache. Documented as a v2 concern (capability-token + per-invocation outcome table) rather than a fix here, since the human adapter is single-operator and the plan does not promise concurrent semantics.
- Files touched: `harness/executor.py` (new, ~160 lines), `harness/adapters/__init__.py` (new, 7 lines), `harness/adapters/human.py` (new, ~95 lines), `tests/test_executor.py` (new, 9 tests), `tests/test_human_adapter.py` (new, 6 tests including 2 coverage).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 1 medium (patched) / 2 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/executor.py:_register_human` | Wrapping the `from harness.adapters.human import HumanAdapter` in `try/except ImportError` silently swallows a real bug (the adapter package is part of the project; an ImportError means the install is broken). The plan called for this guard "for slim installs" but in practice it just hides breakages | medium | Reading the import path: `harness.adapters.human` is a sibling module inside the same source tree; ImportError only fires if the package itself is broken | **patched**: dropped the try/except; the import is unconditional so a missing human adapter raises immediately |
| 2 | `harness/adapters/human.py` (test convenience alias) | Module-level `SUPPORTED_CAPABILITIES = HumanAdapter.SUPPORTED_CAPABILITIES` and `__all__` re-exports were added so tests could import the constant directly; tests now read it as `HumanAdapter.SUPPORTED_CAPABILITIES` via the class attribute, making the alias dead code | low | Grep shows no test imports `SUPPORTED_CAPABILITIES` from the module top-level after the fixture update | **patched**: removed the alias and trimmed `__all__` |
| 3 | Coverage: missing `get` + `unregister` | Plan AC 9 covers manifest validation only; `get` raising KeyError for missing adapters and `unregister` clearing the registry were not exercised | low | Both are part of the public AdapterRegistry surface; tests cover only the happy path of `get` (via `start`/`status`) | **patched**: added `test_get_unknown_adapter_raises_keyerror` and `test_unregister_removes_adapter_and_manifest` |

Other findings reviewed and rejected:
- `HumanAdapter.status(invocation_id)` ignores the invocation_id parameter and returns the single `_last_outcome` cache — concurrent invocations would see the wrong outcome. This is a v2 concern (capability-token + per-invocation outcome table); the human adapter is single-operator for v1 and the plan does not promise concurrent semantics. Deferred.
- `AdapterRegistry` lacks `__contains__` / `__len__` — defer until a consumer needs them; current tests use `.list()` + `in`.
- Runtime check that the registered adapter actually has `start`/`cancel`/`status` methods — would need `isinstance` against `StepExecutorPort` (runtime_checkable Protocol); currently the registry trusts the manifest. Adding the check would catch a future buggy adapter at registration time; defer to v2 since the only adapter is `human` and it's hand-verified.

Verification after patches: `uv run pytest` → 47 passed (10 canonical + 9 executor + 6 human-adapter + 9 layer-boundaries + 4 ports + 9 signing); `uv run python tools/check_layer_boundaries.py` → exit 0; `from harness.executor import ADAPTER_REGISTRY; ADAPTER_REGISTRY.list()` → `['human']`.

## Design Notes

The `AdapterRegistry` is intentionally a module-level singleton (`ADAPTER_REGISTRY`), not a class instance held by a `harness` object. This matches the spec's "sole writer" pattern (AD-4, AD-22) and lets the `human` adapter register itself at module-import time without any explicit boot sequence. Future adapters register at their own import time (e.g. `harness/adapters/pi.py` calls `ADAPTER_REGISTRY.register(...)` at the bottom of the module). To avoid circular imports, `harness/executor.py` imports `harness.adapters.human` inside a `try/except ImportError` — the human adapter is required for v1 but the import guard keeps the registry usable even if the adapter package is missing in a slim install.

`AdapterManifest` is a TypedDict, not a dataclass or Pydantic model, because the registry's validation is pure-string checks (no nested types) and TypedDict gives type-checker support without runtime overhead. The `auth_mode` literal `{"bearer", "oauth", "cli-resident", "human"}` is enforced at registration time, not at type-check time, because TypedDict cannot enforce a closed enum on a string field.

The human adapter's `start` blocks on `input()` rather than spawning a separate prompt mechanism. The v1 single-node harness treats the operator console as the only UI surface (per spec / PRD A6 / NFR-Privacy-1); a CLI prompt is the simplest possible UI. v2 (or a future story) can introduce a non-blocking `start` that returns `AdapterOutcome(status="pending")` and a `poll` method that the Workflow Controller checks later.

The story does NOT add `Harness signing key` invocation for adapter manifest validation. AD-10d says adapters declare their auth mode in a manifest file; signing the manifest is a v2 concern (the operator who installs an adapter signs it locally; cross-org validation is not in v1).

## Verification

**Commands:**
- `uv run pytest tests/test_executor.py tests/test_human_adapter.py -v` -- expected: exit 0, 13 passed.
- `uv run pytest` -- expected: exit 0, all tests pass (canonical + signing + layer-boundaries + ports + executor + human-adapter).
- `uv run python -c "from harness.executor import ADAPTER_REGISTRY; print(ADAPTER_REGISTRY.list())"` -- expected: prints `['human']`.
- `uv lock --check` -- expected: exit 0.

**Manual checks (if no CLI):**
- Verify `harness/executor.py` is the only writer/reader of the registry (no other module imports `AdapterRegistry`).
- Verify `harness/adapters/human.py` does not call `input()` at import time (the boot registration is silent).
