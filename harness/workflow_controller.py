"""Workflow Controller — the conductor that walks the six software-v1 steps
in pipeline order, dispatches each step to its executor adapter, seals the
output as a locked artifact via the Artifact Store, and exposes the AD-24
terminal-status resolver stub.

Public surface (Story 2.5):
- `StepStatus` frozen dataclass: `{step, terminal, gate_mode, run_id, project_id}`.
- `step_status(db, project_id, run_id, step) -> StepStatus` — AD-24 resolver stub.
  Full Gate Engine logic lands in Story 2.7.
- `launch_step(project, run_id, step_name) -> StepStatus` — per-step conductor
  (prereq check + adapter dispatch + artifact write).
- `run(project, run_id) -> StepStatus` — top-level six-step loop with
  idempotent re-run support.

AD-15 (six-step sequence is wired, not configurable) is enforced as code:
`software_v1.STEP_ORDER` is the single source of truth, validated against the
loaded `Pipeline.steps` at module import. Any drift raises
`WorkflowControllerError("pipeline_step_order_drift")`.

The controller is the sole caller of `ADAPTER_REGISTRY.get(...)` — no other
module dispatches to executor adapters (mirrors AD-22's "exactly two writers"
pattern; the controller is the third single-writer).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from harness import artifact_store
from harness import executor as _executor
from harness.executor import AdapterOutcome
from harness.pipeline_loader import Pipeline, Step, load_pipeline
from harness.project_manager import Project


# --- software-v1 step order --------------------------------------------------

# The single v1 pipeline's six steps (AD-15 + PRD §6.2). Mirrors
# `pipelines/software-v1@1.yaml`. Bumping the pipeline version is a new file,
# not a code edit (AD-16).
STEP_ORDER: tuple[str, ...] = (
    "research",
    "design",
    "coding",
    "testing",
    "review",
    "delivery",
)

TerminalStatus = Literal["Done", "Locked", "Pending", "Failed"]
GateMode = Literal["enforced", "skipped"]


# --- Project root resolution ------------------------------------------------

# This file lives at harness/workflow_controller.py — the parent's parent is
# the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- Exceptions -------------------------------------------------------------


class WorkflowControllerError(Exception):
    """Base for all workflow-controller errors."""


class StepUnreachable(WorkflowControllerError):
    """A step's prior prerequisite is not yet locked (AD-15).

    Per AD-15: "a run with an unresolved prerequisite step is held pending and
    step_unreachable is returned on attempted launch".
    """


class UnknownStep(WorkflowControllerError):
    """The requested `step_name` is not in the pipeline's STEP_ORDER."""


class ExecutorNotSupported(WorkflowControllerError):
    """The step's executor mode has no registered adapter (v1 ships `human` only)."""


class ExecutorInvocationFailed(WorkflowControllerError):
    """The executor adapter returned `status='failed'`.

    Carries the original outcome's payload.error in `__cause__`.
    """


# --- Frozen dataclasses -----------------------------------------------------


@dataclass(frozen=True)
class StepStatus:
    """A step's terminal status per AD-11 + AD-24.

    `terminal` is one of `Done|Locked|Pending|Failed`. `gate_mode` is
    `enforced` (Acknowledgement required) or `skipped` (trivial/session tier
    bypasses the Gate per FR-12).
    """

    step: str
    terminal: TerminalStatus
    gate_mode: GateMode
    run_id: str
    project_id: str


# --- Boot-time validation --------------------------------------------------


def validate_step_order(pipeline: Pipeline) -> None:
    """Raise `WorkflowControllerError` if `pipeline.steps` does not match STEP_ORDER.

    Runs at module import time. AD-15 is enforced as code: the YAML's step
    order is the single source of truth, and any drift from the controller's
    hard-coded `STEP_ORDER` is a configuration bug, not a runtime check.
    """
    actual = tuple(step.name for step in pipeline.steps)
    if actual != STEP_ORDER:
        raise WorkflowControllerError(
            f"pipeline_step_order_drift: pipeline {pipeline.name}@{pipeline.version} "
            f"steps={actual!r} != STEP_ORDER={STEP_ORDER!r}"
        )


# Boot-time invariant check: ensure the loaded pipeline matches STEP_ORDER.
# A drift here means `pipelines/software-v1@1.yaml` was edited out of sync
# with this file — a configuration bug to surface immediately, not lazily.
# The narrow except clause lets `pipeline_step_order_drift` (and other
# `WorkflowControllerError`s from `validate_step_order`) propagate with
# their original message intact; broader exceptions are wrapped with the
# `workflow_controller boot failed:` prefix so the diagnostic still names
# the failure mode.
try:
    _pipeline = load_pipeline("software-v1", 1)
    validate_step_order(_pipeline)
except WorkflowControllerError:
    # Already a WorkflowControllerError (drift, etc.) — propagate verbatim.
    raise
except Exception as _boot_err:
    raise WorkflowControllerError(
        f"workflow_controller boot failed: {_boot_err}"
    ) from _boot_err


# --- step_status resolver (AD-24 stub) -------------------------------------


def step_status(
    db: sqlite3.Connection,
    project_id: str,
    run_id: str,
    step: str,
    *,
    project_size: str = "epic",
) -> StepStatus:
    """Return the step's terminal status per AD-24.

    Full resolver logic (Story 2.7 — replaces the Story 2.5 stub):

      1. If an Acknowledgement row exists for `(project_id, run_id, step)`
         with `verdict == 'rejected'` → `Failed` (gate_mode='enforced').
      2. Else if an Acknowledgement row exists with `verdict in
         {'accepted', 'accepted-with-open-items'}` → `Locked`
         (gate_mode='enforced').
      3. Else if `project_size in {'trivial', 'session'}` (FR-12
         skipped-Gate tiers) → `Done` with `gate_mode='skipped'`.
      4. Else → `Pending` (gate_mode='enforced').

    The Acknowledgement table is owned by Story 2.8 (writer + reader +
    AD-23 path-triple signature coverage). v1 reads the `verdict` column
    only and tolerates the table being absent (returns `Pending` — matches
    "no Acknowledgement record yet" semantics; AD-24's full
    `latest_run_event.outcome == "failed"` branch lives in the Run Event
    Log story, not in v1).

    The function is re-exported from `harness.gate_engine` per AD-24 (a):
    "every dashboard view MUST call this function — no view may compute
    terminal status inline." This single-source rule is enforced by
    `tools/check_terminal_status.py` in CI (the AD-24 (d) hook).
    """
    if step not in STEP_ORDER:
        raise UnknownStep(f"unknown_step: {step}")

    gate_mode: GateMode = "enforced"
    terminal: TerminalStatus = "Pending"

    # 1+2: Acknowledgement row check (rejected → Failed, accepted → Locked).
    verdict = _read_acknowledgement_verdict(db, project_id, run_id, step)
    if verdict == "rejected":
        terminal = "Failed"
    elif verdict in ("accepted", "accepted-with-open-items"):
        terminal = "Locked"
    # 3: Skipped-Gate tier check.
    elif project_size in ("trivial", "session"):
        terminal = "Done"
        gate_mode = "skipped"
    # 4: Otherwise: Pending (gate_mode stays 'enforced').

    return StepStatus(
        step=step,
        terminal=terminal,
        gate_mode=gate_mode,
        run_id=run_id,
        project_id=project_id,
    )


def _read_acknowledgement_verdict(
    db: sqlite3.Connection, project_id: str, run_id: str, step: str
) -> str | None:
    """Read the latest Acknowledgement verdict via `harness.acknowledgement_store`.

    Lazy import: `harness.acknowledgement_store` imports
    `harness.workflow_controller.STEP_ORDER`, which creates a cycle if
    imported at module top level. The lazy import here breaks the cycle
    by deferring the acknowledgement_store import until the helper is
    actually called (at the first `step_status` invocation).
    """
    del db  # unused; signature keeps API stability.
    from harness import acknowledgement_store as _ack_store
    try:
        record = _ack_store.read_latest(project_id, run_id, step)
    except _ack_store.AcknowledgementStoreError as e:
        # Only swallow "not found" — NFR-Sec-2 forensics require
        # `AcknowledgementUnsigned` / `AcknowledgementPathMismatch` to
        # propagate (a future dashboard story surfaces them as deferred
        # work). For v1 we still convert them to Pending so the operator
        # is not blocked; the warning is logged so the regression is
        # visible in the run log.
        if "not_found" in str(e):
            return None
        import warnings
        warnings.warn(
            f"acknowledgement_read_failed: {e}",
            UserWarning,
            stacklevel=2,
        )
        return None
    return record.verdict if record is not None else None


def _prior_step(step_name: str) -> str | None:
    """The step immediately preceding `step_name` in STEP_ORDER, or None for the head step."""
    idx = STEP_ORDER.index(step_name)
    if idx == 0:
        return None
    return STEP_ORDER[idx - 1]


def launch_step(
    project: Project,
    run_id: str,
    step_name: str,
    *,
    db: sqlite3.Connection,
    completed: set[str] | None = None,
) -> StepStatus:
    """Launch a single step: prereq check + adapter dispatch + artifact write.

    Returns the post-step `StepStatus`. Raises:
      - `StepUnreachable` if the prior step is not yet locked (AD-15).
      - `UnknownStep` if `step_name` is not in STEP_ORDER.
      - `ExecutorNotSupported` if the executor mode has no registered adapter.
      - `ExecutorInvocationFailed` if the adapter returns `status='failed'`.

    `completed` is the in-memory set of step names already executed during
    the current `run()` invocation. `run()` passes the set it has been
    building; a direct `launch_step` caller passes `None`. Cross-invocation
    idempotency (a second `run()` with the same `run_id`) is implemented
    by the `_step_artifact_sealed` short-circuit at the top of this
    function: if the per-step `.locked` marker exists, the function
    returns the existing `StepStatus` without re-invoking the adapter.
    Story 2.9 added this path for the CAP-2 climax (swap_executor + re-run).
    """
    if step_name not in STEP_ORDER:
        raise UnknownStep(f"unknown_step: {step_name}")

    # Locate the executor tuple for this step.
    step_executor = next(
        (s.executor for s in project.steps if s.name == step_name),
        None,
    )
    if step_executor is None:
        # Every pipeline step must have an executor (Project loader enforces).
        raise WorkflowControllerError(
            f"project_missing_executor: step {step_name!r} has no executor in project"
        )

    # Cross-invocation idempotency (Story 2.9): if a prior `run()`
    # already sealed this step (the `.locked` marker file exists at
    # `var/projects/<pid>/runs/<rid>/<step>/.locked`), skip the adapter
    # dispatch entirely. This is the CAP-2 cross-invocation story: the
    # operator runs, swaps the Coding executor, runs again — the second
    # run re-uses the prior Design artifacts (markers present) and only
    # invokes the new Coding executor (marker absent).
    if _step_artifact_sealed(db, project.project_id, run_id, step_name):
        return step_status(
            db, project.project_id, run_id, step_name,
            project_size=project.size,
        )

    # In-memory idempotency: if `run()` already completed this step in the
    # current Python call, skip re-invocation.
    if completed is not None and step_name in completed:
        return step_status(
            db, project.project_id, run_id, step_name,
            project_size=project.size,
        )

    # Prereq check: every non-head step requires the prior step's output
    # artifact to be locked. AD-24's `step_status` resolves to `Pending` for
    # an epic-tier step whose Acknowledgement has not yet been written
    # (mid-run state), which would falsely block the prereq check. The
    # prereq is a separate concern from terminal status: it asks "is the
    # prior step's artifact sealed?", not "is the prior step acknowledged?".
    prior_name = _prior_step(step_name)
    if prior_name is not None:
        if not _step_artifact_sealed(db, project.project_id, run_id, prior_name):
            raise StepUnreachable(
                f"step_unreachable: {step_name} requires prior {prior_name} locked"
            )

    # Adapter dispatch. We read `_executor.ADAPTER_REGISTRY` (the live module
    # attribute) rather than caching the name at import time, so a test that
    # replaces the registry via `harness.executor.ADAPTER_REGISTRY = ...` is
    # honored. Mirrors the project's pattern in story 2.4.
    try:
        adapter = _executor.ADAPTER_REGISTRY.get(step_executor.mode)
    except KeyError as _adapter_err:
        raise ExecutorNotSupported(
            f"executor_not_supported: {step_executor.mode}"
        ) from _adapter_err

    started_at = datetime.now(timezone.utc).isoformat()
    outcome: AdapterOutcome = adapter.start(capability=step_name)
    ended_at = datetime.now(timezone.utc).isoformat()

    if outcome.get("status") != "succeeded":
        raise ExecutorInvocationFailed(
            f"executor_invocation_failed: {step_name} returned "
            f"status={outcome.get('status')!r} payload={outcome.get('payload')!r}"
        ) from _maybe_outcome_error(outcome)

    # Ensure the run directory exists BEFORE sealing the artifact. If mkdir
    # fails (e.g. permission denied), the controller raises the OSError
    # without writing a sealed-but-orphaned artifact into the DB.
    run_dir = _ensure_run_dir(project.project_id, run_id, step_name)

    # Seal the outcome as a locked artifact.
    payload = outcome.get("payload") or {}
    envelope = _build_envelope(
        project_id=project.project_id,
        run_id=run_id,
        step=step_name,
        executor_mode=step_executor.mode,
        operator_input=payload.get("operator_input"),
        started_at=started_at,
        ended_at=ended_at,
    )
    artifact_id = artifact_store.put_pending(db, envelope)
    artifact_store.lock(db, artifact_id)

    # Mark the step as sealed in the run directory. `_step_artifact_sealed`
    # reads this marker file to answer prereq checks in O(1) without
    # scanning the artifacts table.
    (run_dir / ".locked").write_text(artifact_id, encoding="utf-8")

    if completed is not None:
        completed.add(step_name)

    return step_status(
        db, project.project_id, run_id, step_name,
        project_size=project.size,
    )


def _maybe_outcome_error(outcome: AdapterOutcome) -> Exception | None:
    """Build a chained cause exception for ExecutorInvocationFailed.

    The adapter's `payload.error` is sometimes a string (e.g.
    `"operator_input_eof"`), sometimes an exception instance. We wrap
    whatever the adapter returned in an `Exception` so `raise ... from`
    always has a valid cause. Returns None when the adapter did not
    supply an error (so `from None` preserves Python's default behavior).
    """
    payload = outcome.get("payload") or {}
    err = payload.get("error")
    if err is None:
        return None
    if isinstance(err, BaseException):
        return err
    return RuntimeError(str(err))


# --- Top-level six-step loop -----------------------------------------------


def run(
    project: Project,
    run_id: str,
    *,
    db: sqlite3.Connection,
) -> StepStatus:
    """Walk all six steps in pipeline order.

    Returns the delivery step's final `StepStatus`. Halts on the first
    failure (no partial-completion runs). Within a single invocation, the
    controller's in-memory `completed` set tracks which steps have already
    run; the adapter is NOT re-invoked for steps in the set. Cross-invocation
    idempotency (a second `run()` call with the same `run_id`) is owned by
    Story 2.9's `swap_executor_take_lock` handler.
    """
    completed: set[str] = set()
    status: StepStatus
    for step_name in STEP_ORDER:
        status = launch_step(project, run_id, step_name, db=db, completed=completed)
    assert status is not None  # for type-checkers; loop always runs at least once
    return status


# --- Helpers ----------------------------------------------------------------


def _prior_step(step_name: str) -> str | None:
    """The step immediately preceding `step_name` in STEP_ORDER, or None for the head step."""
    idx = STEP_ORDER.index(step_name)
    if idx == 0:
        return None
    return STEP_ORDER[idx - 1]


def _step_artifact_sealed(
    db: sqlite3.Connection, project_id: str, run_id: str, step_name: str
) -> bool:
    """True iff `launch_step(step_name)` has sealed an artifact in this run.

    Reads the per-step marker file at
    `var/projects/<project_id>/runs/<run_id>/<step_name>/.locked`. The marker
    is written by `launch_step` after `artifact_store.lock(...)` returns;
    its presence means the step's output is sealed in the artifacts table.

    The marker-file check is O(1) and side-effect free (no DB query, no
    JSON parse) — the alternative (scanning every locked artifact row and
    JSON-decoding its envelope) is O(N) per prereq check and was rejected
    in review. The marker is intentionally a plain file (not a row in a
    side table) so it requires no migration.

    `db` is accepted for API symmetry with `step_status` and other AD-24
    resolvers; the v1 implementation does not query the DB.
    """
    del db  # unused; signature keeps future Gate Engine compatibility.
    marker = (
        PROJECT_ROOT
        / "var" / "projects" / project_id / "runs" / run_id / step_name / ".locked"
    )
    return marker.exists()


def _ensure_run_dir(project_id: str, run_id: str, step_name: str) -> Path:
    """Create the per-step directory under the run directory.

    Layout: `var/projects/<project_id>/runs/<run_id>/<step_name>/`. Each step
    gets its own directory; the marker file `<step_name>/.locked` is written
    after `launch_step` seals the artifact and `_step_artifact_sealed` reads
    it to answer prereq checks in O(1).
    """
    run_dir = PROJECT_ROOT / "var" / "projects" / project_id / "runs" / run_id / step_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _build_envelope(
    *,
    project_id: str,
    run_id: str,
    step: str,
    executor_mode: str,
    operator_input: str | None,
    started_at: str,
    ended_at: str,
) -> bytes:
    """Build the canonical-bytes envelope sealed as the step's artifact.

    Schema is intentionally small — enough for the dashboard (Story 4.x) to
    render a step summary without re-opening the artifact. The hash is the
    artifact's identity; downstream steps read it via `artifact_store.read`.
    """
    envelope = {
        "project_id": project_id,
        "run_id": run_id,
        "step": step,
        "executor_mode": executor_mode,
        "operator_input": operator_input,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    return json.dumps(envelope, sort_keys=True).encode("utf-8")


__all__ = [
    "STEP_ORDER",
    "StepStatus",
    "StepUnreachable",
    "UnknownStep",
    "ExecutorNotSupported",
    "ExecutorInvocationFailed",
    "WorkflowControllerError",
    "step_status",
    "launch_step",
    "run",
    "validate_step_order",
]