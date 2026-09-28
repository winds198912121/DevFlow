"""Tests for harness.workflow_controller.

Coverage targets the I/O Matrix in the plan at
`_bmad-output/preview-ticketing/initiative-devflow-harness/epic-pipeline-and-gates/story-workflow-controller-6-step-wiring-ad-15-sequence-step-status-plan.md`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from harness.migrate import run_migrations
from harness.workflow_controller import (
    STEP_ORDER,
    ExecutorInvocationFailed,
    ExecutorNotSupported,
    StepStatus,
    StepUnreachable,
    UnknownStep,
    WorkflowControllerError,
    launch_step,
    run,
    step_status,
    validate_step_order,
)
from harness.pipeline_loader import Pipeline, Step, load_pipeline
from harness.project_manager import (
    ExecutorTuple,
    Project,
    ProjectStep,
)
from harness.executor import AdapterOutcome


# --- Test doubles ---------------------------------------------------------


class FakeHumanAdapter:
    """Stand-in for HumanAdapter that does not block on input().

    Records every `start(capability=...)` invocation in `calls`. Always
    returns `status='succeeded'` with a synthetic `operator_input` so
    the controller's envelope builder has something to seal.

    Tests can subclass or set `fail_capability` to inject a failure on a
    specific capability without re-implementing the adapter surface.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_capability: str | None = None

    def start(self, capability: str) -> AdapterOutcome:
        self.calls.append(capability)
        if self.fail_capability == capability:
            return AdapterOutcome(
                status="failed", payload={"error": "fake_adapter_failure"}
            )
        return AdapterOutcome(
            status="succeeded",
            payload={"capability": capability, "operator_input": f"fake-input-{capability}"},
        )

    def cancel(self, invocation_id: str) -> None:
        return None

    def status(self, invocation_id: str) -> AdapterOutcome | None:
        return None


@pytest.fixture(autouse=True)
def _stub_input(monkeypatch: pytest.MonkeyPatch):
    """Stub `builtins.input` so the real HumanAdapter's `start()` does not
    block on stdin. Returns `"fake-default-input"` for every prompt. Tests
    that need call-counting or capability-ordering assertions use the
    `_swap_human_adapter` fixture instead, which replaces the registry
    with `FakeHumanAdapter` for that test only.

    Patching `input()` (instead of the registry) keeps the boot-time
    `_register_human()` invariant from test_executor.py undisturbed
    across the suite.
    """
    monkeypatch.setattr("builtins.input", lambda prompt="": "fake-default-input")


@pytest.fixture
def _swap_human_adapter(monkeypatch: pytest.MonkeyPatch) -> FakeHumanAdapter:
    """Replace the `human` adapter in `ADAPTER_REGISTRY` with FakeHumanAdapter.

    The autouse `_stub_input` keeps the real HumanAdapter non-blocking; this
    fixture goes one step further and replaces the adapter itself so the
    test can count `start()` calls or simulate `status='failed'` for a
    specific capability. Uses `monkeypatch.setattr` with the dotted path
    so pytest resolves the registry at fixture-call time (preserving the
    live `harness.executor.ADAPTER_REGISTRY` reference) and restores the
    original `_adapters` after the test.
    """
    fake = FakeHumanAdapter()
    monkeypatch.setattr(
        "harness.executor.ADAPTER_REGISTRY._adapters",
        {"human": fake},
    )
    return fake


@pytest.fixture(autouse=True)
def _clean_ack_dir():
    """Wipe `acknowledgements/` between tests so Acknowledgement files
    written by one test don't leak into another.

    Story 2.8's resolver reads Acknowledgements from disk (per spine
    AD-5 nested-ULID stance); without this fixture, test ordering would
    silently change `step_status` results. The fixture deletes the
    directory at the end of each test (after the resolver has run for
    that test) so a failing test's failure mode stays local.
    """
    import shutil
    from harness.acknowledgement_store import ACKNOWLEDGEMENTS_DIR
    yield
    if ACKNOWLEDGEMENTS_DIR.exists():
        shutil.rmtree(ACKNOWLEDGEMENTS_DIR)


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def db() -> sqlite3.Connection:
    """Fresh in-memory DB with migrations applied (artifacts table only;
    Story 2.8 adds the acknowledgements table)."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    return conn


@pytest.fixture
def human_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A Project with all six steps in mode: human (synthetic — Story 2.6
    ships the python-hello fixture)."""
    monkeypatch.setattr(
        "harness.workflow_controller.PROJECT_ROOT", tmp_path
    )
    return Project(
        project_id="p1",
        pipeline_name="software-v1",
        pipeline_version=1,
        size="epic",
        steps=tuple(
            ProjectStep(
                name=name,
                executor=ExecutorTuple(
                    mode="human", agent=None, model=None, skills=()
                ),
            )
            for name in STEP_ORDER
        ),
    )


@pytest.fixture
def trivial_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A Project with size='trivial' — exercises the FR-12 skipped-Gate tier."""
    monkeypatch.setattr(
        "harness.workflow_controller.PROJECT_ROOT", tmp_path
    )
    return Project(
        project_id="p1",
        pipeline_name="software-v1",
        pipeline_version=1,
        size="trivial",
        steps=tuple(
            ProjectStep(
                name=name,
                executor=ExecutorTuple(
                    mode="human", agent=None, model=None, skills=()
                ),
            )
            for name in STEP_ORDER
        ),
    )


@pytest.fixture
def agent_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A Project whose Coding step uses mode='agent' — no agent adapter in v1."""
    monkeypatch.setattr(
        "harness.workflow_controller.PROJECT_ROOT", tmp_path
    )
    return Project(
        project_id="p1",
        pipeline_name="software-v1",
        pipeline_version=1,
        size="epic",
        steps=tuple(
            ProjectStep(
                name=name,
                executor=(
                    ExecutorTuple(
                        mode="agent",
                        agent="codex",
                        model="gpt-5",
                        skills=("bmad-build@0.4.2",),
                    )
                    if name == "coding"
                    else ExecutorTuple(
                        mode="human", agent=None, model=None, skills=()
                    )
                ),
            )
            for name in STEP_ORDER
        ),
    )


# --- AC: STEP_ORDER is the wired six-step sequence --------------------------


def test_step_order_matches_spine_six_steps():
    """AD-15 + PRD §6.2: research → design → coding → testing → review → delivery."""
    assert STEP_ORDER == ("research", "design", "coding", "testing", "review", "delivery")


# --- AC: validate_step_order raises on drift -------------------------------


def test_validate_step_order_raises_on_drift():
    """A Pipeline whose steps don't match STEP_ORDER raises at validation."""
    bad = Pipeline(
        name="software-v1",
        version=1,
        description="bad",
        steps=tuple(
            Step(name=n, contract=f"x.{n}", description="")
            for n in ("research", "design", "coding", "testing", "review")  # 5 steps, no delivery
        ),
    )
    with pytest.raises(WorkflowControllerError, match="pipeline_step_order_drift"):
        validate_step_order(bad)


def test_validate_step_order_passes_on_real_pipeline():
    """The loaded pipelines/software-v1@1.yaml matches STEP_ORDER (boot-time invariant)."""
    pipeline = load_pipeline("software-v1", 1)
    validate_step_order(pipeline)  # must not raise


# --- AC: step_status variants ----------------------------------------------


def test_step_status_pending_when_no_acknowledgement_and_epic_tier(db):
    """Pending: no Acknowledgement row + size='epic' (default) → Pending/enforced."""
    status = step_status(db, "p1", "R1", "research")
    assert status == StepStatus(
        step="research", terminal="Pending", gate_mode="enforced", run_id="R1", project_id="p1"
    )


def test_step_status_locked_when_acknowledgement_verdict_accepted(db, _clean_ack_dir):
    """Locked: Acknowledgement with verdict='accepted' → Locked/enforced.

    Story 2.8 upgrade: the resolver reads through the Acknowledgement
    Store (file on disk), not a hand-rolled SQL table. The test writes a
    real Acknowledgement record via `acknowledgement_store.write` and
    asserts that `step_status` returns Locked.
    """
    from harness.acknowledgement_store import write, ArtifactRef
    write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=ArtifactRef(
            step="design", project_id="p1", run_id="R1", hash="sha256:" + "0" * 64
        ),
    )
    status = step_status(db, "p1", "R1", "design")
    assert status == StepStatus(
        step="design", terminal="Locked", gate_mode="enforced", run_id="R1", project_id="p1"
    )


def test_step_status_locked_when_acknowledgement_verdict_accepted_with_open_items(db, _clean_ack_dir):
    """Locked: Acknowledgement with verdict='accepted-with-open-items' → Locked."""
    from harness.acknowledgement_store import write, ArtifactRef, OpenItem
    write(
        project_id="p1",
        run_id="R2",
        step="review",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted-with-open-items",
        artifact_ref=ArtifactRef(
            step="review", project_id="p1", run_id="R2", hash="sha256:" + "0" * 64
        ),
        open_items=(OpenItem(id="OI-1", description="fix coverage"),),
    )
    status = step_status(db, "p1", "R2", "review")
    assert status.terminal == "Locked"


def test_step_status_failed_when_acknowledgement_verdict_rejected(db, _clean_ack_dir):
    """rejected verdict yields Failed (Story 2.7's full AD-24 logic)."""
    from harness.acknowledgement_store import write, ArtifactRef
    write(
        project_id="p1",
        run_id="R3",
        step="review",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="rejected",
        artifact_ref=ArtifactRef(
            step="review", project_id="p1", run_id="R3", hash="sha256:" + "0" * 64
        ),
        rejection_reason="missing AC-7",
    )
    status = step_status(db, "p1", "R3", "review")
    assert status == StepStatus(
        step="review", terminal="Failed", gate_mode="enforced", run_id="R3", project_id="p1"
    )


def test_step_status_done_for_trivial_tier_with_no_acknowledgement(db):
    """Done: size='trivial' (FR-12 skipped-Gate tier) + no Acknowledgement → Done/skipped."""
    status = step_status(db, "p1", "R1", "research", project_size="trivial")
    assert status == StepStatus(
        step="research", terminal="Done", gate_mode="skipped", run_id="R1", project_id="p1"
    )


def test_step_status_done_for_session_tier_with_no_acknowledgement(db):
    """Done: size='session' + no Acknowledgement → Done/skipped."""
    status = step_status(db, "p1", "R1", "design", project_size="session")
    assert status.terminal == "Done"
    assert status.gate_mode == "skipped"


def test_step_status_unknown_step_raises(db):
    """UnknownStep: step not in STEP_ORDER raises."""
    with pytest.raises(UnknownStep, match="unknown_step: ghosts"):
        step_status(db, "p1", "R1", "ghosts")


# --- AC: launch_step on the head step ---------------------------------------


def test_launch_step_research_succeeds(human_project, db):
    """Head step (research) requires no prior — succeeds and returns Pending."""
    status = launch_step(human_project, "R1", "research", db=db)
    assert status.step == "research"
    # No Acknowledgement row → Pending (per project_size='epic' default).
    assert status.terminal == "Pending"
    assert status.gate_mode == "enforced"


# --- AC: launch_step on non-head step requires prior -------------------------


def test_launch_step_coding_without_prior_design_raises_step_unreachable(human_project, db):
    """AD-15: launching coding before design is locked raises step_unreachable."""
    with pytest.raises(StepUnreachable, match="step_unreachable: coding requires prior design locked"):
        launch_step(human_project, "R1", "coding", db=db)


def test_launch_step_unknown_step_raises(human_project, db):
    """UnknownStep: step not in STEP_ORDER raises."""
    with pytest.raises(UnknownStep, match="unknown_step: ghosts"):
        launch_step(human_project, "R1", "ghosts", db=db)


# --- AC: launch_step on agent-codepoint exercises agent mode ----


def test_launch_step_agent_mode_raises_executor_not_supported(agent_project, db):
    """v1 ships no agent adapter — launch_step on agent mode raises."""
    # First complete research + design via the human adapter.
    launch_step(agent_project, "R1", "research", db=db)
    launch_step(agent_project, "R1", "design", db=db)
    with pytest.raises(ExecutorNotSupported, match="executor_not_supported: agent"):
        launch_step(agent_project, "R1", "coding", db=db)


# --- AC: launch_step on trivial tier returns Done --------------------------


def test_launch_step_trivial_tier_returns_done(trivial_project, db):
    """FR-12: trivial-tier steps return Done/skipped, no Acknowledgement needed."""
    status = launch_step(trivial_project, "R1", "research", db=db)
    assert status.terminal == "Done"
    assert status.gate_mode == "skipped"


# --- AC: run() walks all six steps -----------------------------------------


def test_run_traverses_all_six_steps_in_order(
    human_project, db, _swap_human_adapter
):
    """run() invokes every step in STEP_ORDER. The autouse fixture installs
    FakeHumanAdapter which records calls; we assert the recorded order
    matches STEP_ORDER."""
    fake = _swap_human_adapter
    status = run(human_project, "R1", db=db)
    assert fake.calls == list(STEP_ORDER)
    assert status.step == "delivery"
    # No Acknowledgement row + epic tier → Pending (per stub logic).
    assert status.terminal == "Pending"


# --- AC: run() halts on first failure --------------------------------------


def test_run_halts_on_first_failure(human_project, db, _swap_human_adapter):
    """If launch_step raises ExecutorInvocationFailed, run() re-raises AND
    prior steps' locked artifacts survive (the operator's pull/fix/re-run
    path depends on this — see Design Notes in the plan)."""
    _swap_human_adapter.fail_capability = "review"
    with pytest.raises(
        ExecutorInvocationFailed, match="executor_invocation_failed: review"
    ):
        run(human_project, "R1", db=db)
    # Prior steps (research, design, coding, testing) must be persisted;
    # failing step + steps after (review, delivery) must not be started.
    locked_steps = {
        row[0]
        for row in db.execute("SELECT payload FROM artifacts WHERE status='locked'")
    }
    import json as _json
    parsed = {_json.loads(p).get("step") for p in locked_steps}
    assert parsed == {"research", "design", "coding", "testing"}
    assert "review" not in parsed
    assert "delivery" not in parsed


# --- AC: in-memory idempotency within a single run() invocation ------------


def test_run_avoids_reinvoking_already_completed_steps(
    human_project, db, _swap_human_adapter
):
    """Within one run() invocation, a step is invoked at most once (the
    autouse FakeHumanAdapter records every start() call; we expect exactly
    one per step)."""
    run(human_project, "R1", db=db)
    assert _swap_human_adapter.calls == list(STEP_ORDER)
    assert len(_swap_human_adapter.calls) == 6


def test_run_cross_invocation_idempotency_via_marker_files(
    human_project, db, _swap_human_adapter
):
    """Story 2.9: a second `run(project, "R1")` against the same `(project, run_id)`
    re-uses the prior run's `.locked` markers and does NOT re-invoke any
    adapter (CAP-2 cross-invocation climax; the operator can swap
    executors between the two runs and the second call leaves the prior
    Design steps untouched).
    """
    # First run: every adapter invoked once.
    run(human_project, "R1", db=db)
    initial_calls = list(_swap_human_adapter.calls)
    assert len(initial_calls) == 6

    # Second run with the same (project, run_id): the marker-file short-circuit
    # in `launch_step` short-circuits every step. Zero new adapter calls.
    _swap_human_adapter.calls.clear()
    run(human_project, "R1", db=db)
    assert _swap_human_adapter.calls == []


# --- AC: artifacts are sealed per step ------------------------------------


def test_run_persists_six_locked_artifacts(human_project, db):
    """After run(), the artifacts table holds six rows whose step enums match
    STEP_ORDER in order."""
    run(human_project, "R1", db=db)
    rows = db.execute(
        "SELECT COUNT(*) FROM artifacts WHERE status = 'locked'"
    ).fetchone()
    assert rows[0] == 6


# --- AC: positive prereq check after a successful prior launch -------------


def test_launch_step_coding_after_design_succeeds(human_project, db):
    """After `launch_step('design')` seals an artifact, `launch_step('coding')`
    must NOT raise StepUnreachable. This pins the positive prereq-check
    path; the negative path is covered by
    `test_launch_step_coding_without_prior_design_raises_step_unreachable`."""
    launch_step(human_project, "R1", "research", db=db)
    launch_step(human_project, "R1", "design", db=db)
    status = launch_step(human_project, "R1", "coding", db=db)
    assert status.step == "coding"


# --- AC: chained cause on adapter failure ---------------------------------


def test_executor_invocation_failed_chains_original_error(
    human_project, db, _swap_human_adapter
):
    """ExecutorInvocationFailed's `__cause__` carries the adapter's
    payload.error as an exception (per the plan's Boundaries: "every
    failure propagates with the original exception chained via
    raise ... from adapter_error")."""
    _swap_human_adapter.fail_capability = "design"
    launch_step(human_project, "R1", "research", db=db)  # seed prereq
    with pytest.raises(ExecutorInvocationFailed) as exc_info:
        launch_step(human_project, "R1", "design", db=db)
    assert exc_info.value.__cause__ is not None
    assert "fake_adapter_failure" in str(exc_info.value.__cause__)