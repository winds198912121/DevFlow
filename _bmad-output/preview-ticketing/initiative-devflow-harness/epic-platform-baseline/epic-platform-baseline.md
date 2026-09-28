---
type: epic
title: "Platform baseline — harness scaffold, signing key, canonical bytes, CI lint"
parent: initiative-devflow-harness
covers: []   # platform baseline carries no parent requirement ids; each entry cites the spine AD it implements
after: []
assignee: ""
risk: high
estimate: ""
estimate_basis: spec
---

# Platform baseline — harness scaffold, signing key, canonical bytes, CI lint

## Description

The opening epic per `slice_to_epics`: a single-node self-hosted harness binary that boots, signs with Ed25519, canonicalizes JSON, enforces layer boundaries in CI, and exposes the ExecutorAdapter port (with a `human` adapter) so the other three epics can run. No CAP-N is delivered here; this epic unblocks them all. Spine ADs implemented: AD-1 (pipeline loading read-only), AD-13 (dashboard read model — partial, no UI yet), AD-17 (canonical serialization), AD-19 (Herdr mirror not joined), AD-21 (dashboard write allowlist at FastAPI import time), AD-22 (skill bump registry has exactly two writers), AD-26 (layer boundary lint).

## Outcome

A developer can run `uv run harness --check-baseline` and the harness exits 0 with: a generated Ed25519 keypair at `var/secrets/harness.key` (0600), a SQLite at `var/harness.sqlite` containing the empty canonical stores, the layer-boundary CI lint passing on the empty `skills/`, `agents/`, `herdr/`, `dashboard/` skeletons, and the `human` adapter registered in the ExecutorAdapter port. Every later epic builds on this scaffold without re-deciding the platform questions.

## Requirements

- AD-17: All `sha256:` hashing in the harness goes through `harness.canonical.canonical_bytes`. CI lint rejects direct `hashlib.sha256` calls outside `harness/canonical.py`. Canonicalization: JSON sorted keys + UTF-8 NFC + LF + no trailing newline; text LF + trailing newline; binary as-is.
- AD-26: `tools/check_layer_boundaries.py` parses every `*.py` under `skills/`, `agents/`, `herdr/`, and rejects imports whose module path begins with `harness.*` except the published allowlist in `harness/ports/__init__.py` (StepExecutorPort, HerdrEventPort, ExecutorTuple, SkillManifest, ArtifactContract, Acknowledgement, ErrorRecord, RunEvent).
- NFR-Sec-1 + NFR-Sec-2: Ed25519 harness keypair at `var/secrets/harness.key` (0600). Key generation from `cryptography.hazmat.primitives.asymmetric.ed25519`. Sign-verify roundtrip available via `harness.signing.sign(value) -> signature` and `harness.signing.verify(value, signature) -> bool`.
- AD-10 (port surface, no adapter implementations yet beyond `human`): `ExecutorAdapter` protocol defined in `harness/ports/step_executor.py` with `start(capability) / cancel(id) / status(id) → outcome`. `human` adapter registered by default at boot.
- AD-21: FastAPI router enforces dashboard write allowlist at import time via `tools/check_dashboard_writes.py` CI lint. Empty allowlist on the baseline run (no writes yet) — lint passes when the allowlist is empty AND no `dashboard/` write routes exist.
- AD-22 (empty state): Skill Bump Registry table exists in `var/harness.sqlite` with exactly two writer paths declared but no implementations yet: `bmad skill_bump register` / `bmad skill_bump promote` (CLI scaffold only).
- AD-19 (empty state): `var/herdr_mirror.sqlite` exists with the schema (Herdr event columns per FR-29) but is empty; the harness-side ingest path is not implemented in this epic.
- PRD §6.2 single-node self-hosted posture: `uv`-pinned Python 3.12.14, lockfiles committed (`uv.lock`), harness runs as a foreground process from `uv run harness`. No cloud-managed dependencies.

## Done when

1. `uv run harness --check-baseline` exits 0 with all baseline invariants satisfied (keypair present, SQLite created, lint passing, `human` adapter registered).
2. `uv run harness.signing.verify` roundtrip succeeds on a sample canonical-bytes value.
3. `tools/check_layer_boundaries.py` passes on the empty `skills/`, `agents/`, `herdr/`, `dashboard/` skeletons.
4. `tools/check_dashboard_writes.py` passes (empty allowlist, no write routes).
5. `uv lock` + `uv sync` from a clean clone produces a bit-identical environment (verified by `uv lock --check`).
6. A 30-line smoke test imports `harness.canonical.canonical_bytes`, `harness.signing.sign`, `harness.signing.verify`, `harness.ports.StepExecutorPort`, and `harness.ports.ExecutorTuple` — all import cleanly.

## Boundaries

The platform scaffold (uv project, FastAPI router, Typer CLI, SQLite schema, signing key generation, CI lint tooling, layer-boundary enforcement). NOT pipeline semantics, NOT step execution, NOT Acknowledgement / error-record writers — those belong to epic-pipeline-and-gates. NOT benchmark, NOT skill bump registry writers — epic-error-benchmark-skill. NOT dashboard UI, NOT cost ledger — epic-dashboard-cost.

## References

- architecture — `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`, AD-1, AD-10 (port only), AD-13, AD-17, AD-19, AD-21, AD-22, AD-26
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`, NFR-Sec-1, NFR-Sec-2, §6.2 single-node self-hosted
- spec — `_bmad-output/specs/spec-devflow/SPEC.md`, Constraints (canonical hashing single function, Ed25519 signing, layer dependency direction)

## Notes

- Decision (2026-09-27): This epic carries no `covers` ids because the platform baseline is the opening epic per `slice_to_epics`; each story cites the spine AD it implements in `covers` as `AD-N`.
- Decision (2026-09-27): A `human` ExecutorAdapter ships in this epic so epic-pipeline-and-gates can demonstrate CAP-1 end-to-end on a sample project without picking Pi/OMP/Codex (OQ-6 still open).
- Decision (2026-09-27): Tracer bullet for this epic is a 30-line smoke test that imports the public API; it is the first story's `verify` line.
- Unknown: exact `var/secrets/harness.key` file mode handling on macOS vs Linux (0600 enforcement). Story 1's `verify` covers the roundtrip, not the mode bits.
- Assumption (2026-09-27): `uv lock` produces bit-identical lockfiles when the platform-stack entries in the spine (§Stack table) match what's actually resolved; the spine's `verified 2026-09-26` notes are trusted at face value.
- Assumption (2026-09-27): Empty `skills/`, `agents/`, `herdr/`, `dashboard/` directories ship with the baseline so `check_layer_boundaries.py` has something to scan; if a directory is missing, the lint exits 0 silently (treat as a future-deferred finding rather than a baseline-blocker).
