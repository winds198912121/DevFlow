"""Tests for harness.gate_engine.

Coverage targets the I/O Matrix in the plan at
`_bmad-output/preview-ticketing/initiative-devflow-harness/epic-pipeline-and-gates/story-quality-gate-engine-step-status-resolver-verdict-vocabulary-plan.md`.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from harness import artifact_store
from harness import gate_engine as _gate_engine
from harness.gate_engine import (
    ContractAlreadyRegistered,
    ContractLookupMiss,
    GateEngineError,
    IdentityContract,
    PydanticSchemaContract,
    TestReportModel,
    UnsignedContractWarning,
    VerifyResult,
    gate_mode_for,
    get_registered_contracts,
    lookup_contract,
    register_contract,
    step_status,
    validate_verdict,
    verify_artifact,
)
from harness.migrate import run_migrations
from harness.workflow_controller import StepStatus


# --- Autouse fixture: reset module-level state --------------------------------
#
# The gate engine keeps two module-level mutables that survive the test
# process:
# - `_warned_keys` (one-shot warning dedup set) — if not reset, the warning
#   test passes only on the first invocation, breaking on
#   `pytest-randomly` reordering or `pytest --repeat`.
# - `_REGISTRY` (boot-time contract registry) — `test_register_contract_twice_raises`
#   adds an entry without cleanup; a later `test_boot_time_registers_six_contracts`
#   assertion `== 6` would silently break.
# Both are reset to their boot-time shape before every test.


@pytest.fixture(autouse=True)
def _reset_gate_engine_state() -> None:
    # Snapshot the boot-time state.
    boot_keys = frozenset(_gate_engine._warned_keys)
    boot_registry = dict(_gate_engine._REGISTRY)
    try:
        yield
    finally:
        # Restore both to their boot-time shape. _REGISTRY keys are
        # the (pipeline, version, step) tuples; values are the contract
        # instances. Restoring via dict() copy preserves the originals.
        _gate_engine._warned_keys.clear()
        _gate_engine._warned_keys.update(boot_keys)
        _gate_engine._REGISTRY.clear()
        _gate_engine._REGISTRY.update(boot_registry)


@pytest.fixture(autouse=True)
def _clean_ack_dir():
    """Wipe `acknowledgements/` between tests (Story 2.8: file-backed store).

    Without this fixture, Acknowledgement files written by one test would
    leak into another, silently changing `step_status` results. The
    fixture runs cleanup at the END of each test (after the resolver
    has executed for that test) so a failing test's failure mode stays
    local.
    """
    import shutil
    from harness.acknowledgement_store import ACKNOWLEDGEMENTS_DIR
    yield
    if ACKNOWLEDGEMENTS_DIR.exists():
        shutil.rmtree(ACKNOWLEDGEMENTS_DIR)


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def db() -> sqlite3.Connection:
    """Fresh in-memory DB with migrations applied (artifacts table only)."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    return conn


def _valid_test_report_payload() -> bytes:
    """A minimal valid test-report.json matching PRD A7."""
    return json.dumps(
        {
            "step": "testing",
            "run_id": "R1",
            "project_id": "p1",
            "executor_tuple": {"agent": "human", "model": "n/a", "skills": []},
            "started_at": "2026-09-28T00:00:00Z",
            "ended_at": "2026-09-28T00:00:01Z",
            "outcome": "pass",
            "cases": [
                {
                    "id": "AC-1",
                    "name": "greet works",
                    "acceptance_ref": "AC-1",
                    "status": "pass",
                }
            ],
            "acceptance_coverage": {"fr_total": 1, "fr_passed": 1},
        },
        sort_keys=True,
    ).encode("utf-8")


# --- AC: Verdict enum ------------------------------------------------------


def test_validate_verdict_accepts_all_three_ad12_values():
    for v in ("accepted", "accepted-with-open-items", "rejected"):
        validate_verdict(v)  # must not raise


def test_validate_verdict_rejects_unknown_value():
    with pytest.raises(ValueError, match="verdict_invalid"):
        validate_verdict("approved")


# --- AC: ContractRegistry + boot-time registration ------------------------


def test_boot_time_registers_six_contracts_for_software_v1():
    """`register_all_v1_contracts()` runs at module import time and registers
    exactly six entries under `(software-v1@1, *)`."""
    registered = get_registered_contracts()
    assert len(registered) == 6


def test_testing_step_uses_pydantic_schema_contract():
    """The `testing` step has a `PydanticSchemaContract` (not an identity)."""
    contract = lookup_contract("software-v1", 1, "testing")
    assert isinstance(contract, PydanticSchemaContract)


def test_other_steps_use_identity_contract():
    """The other five steps use `IdentityContract` (v1 unsigned-contract policy)."""
    for step in ("research", "design", "coding", "review", "delivery"):
        contract = lookup_contract("software-v1", 1, step)
        assert isinstance(contract, IdentityContract), f"{step} should be identity"


def test_register_contract_twice_raises():
    """A second `register_contract` for the same triple raises.

    The autouse `_reset_gate_engine_state` fixture restores `_REGISTRY`
    after this test runs, so other tests' contract-count assertions
    remain stable under pytest-randomly reordering.
    """
    register_contract(
        IdentityContract(),
        pipeline="test-pipeline",
        pipeline_version=99,
        step="custom",
    )
    with pytest.raises(ContractAlreadyRegistered):
        register_contract(
            IdentityContract(),
            pipeline="test-pipeline",
            pipeline_version=99,
            step="custom",
        )


def test_lookup_contract_miss_raises():
    """Looking up an unregistered step raises `ContractLookupMiss`."""
    with pytest.raises(ContractLookupMiss, match="no contract"):
        lookup_contract("test-pipeline", 99, "unknown")


# --- AC: verify_artifact (testing schema path) ---------------------------


def test_verify_artifact_accepts_valid_test_report(db):
    """A locked payload matching the testing schema returns ok=True."""
    payload = _valid_test_report_payload()
    artifact_id = artifact_store.put_pending(db, payload)
    artifact_hash = artifact_store.lock(db, artifact_id)
    result = verify_artifact(db, "p1", "R1", "testing", artifact_hash)
    assert result.ok is True
    assert result.error_code is None
    assert result.contract_path is not None


def test_verify_artifact_rejects_wrong_step_field(db):
    """`step: design` violates the schema's `step.const == "testing"`."""
    payload_dict = json.loads(_valid_test_report_payload().decode("utf-8"))
    payload_dict["step"] = "design"
    payload = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
    artifact_id = artifact_store.put_pending(db, payload)
    artifact_hash = artifact_store.lock(db, artifact_id)
    result = verify_artifact(db, "p1", "R1", "testing", artifact_hash)
    assert result.ok is False
    assert result.error_code == "artifact_contract_mismatch"
    assert "step" in (result.message or "").lower()


def test_verify_artifact_rejects_missing_required_field(db):
    """A payload missing a required field is rejected."""
    payload_dict = json.loads(_valid_test_report_payload().decode("utf-8"))
    del payload_dict["cases"]
    payload = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
    artifact_id = artifact_store.put_pending(db, payload)
    artifact_hash = artifact_store.lock(db, artifact_id)
    result = verify_artifact(db, "p1", "R1", "testing", artifact_hash)
    assert result.ok is False
    assert result.error_code == "artifact_contract_mismatch"


def test_verify_artifact_identity_contract_always_accepts(db):
    """The five unsigned steps use IdentityContract — any payload passes."""
    payload = b"arbitrary bytes - the contract is opaque for unsigned steps"
    artifact_id = artifact_store.put_pending(db, payload)
    artifact_hash = artifact_store.lock(db, artifact_id)
    with pytest.warns(UnsignedContractWarning):
        result = verify_artifact(db, "p1", "R1", "research", artifact_hash)
    assert result.ok is True
    assert result.contract_path is None


def test_verify_artifact_unknown_step_raises(db):
    """No contract registered for the step → ContractLookupMiss propagates."""
    payload = _valid_test_report_payload()
    artifact_id = artifact_store.put_pending(db, payload)
    artifact_hash = artifact_store.lock(db, artifact_id)
    with pytest.raises(ContractLookupMiss):
        verify_artifact(db, "p1", "R1", "unknown_step", artifact_hash)


# --- AC: step_status full resolver (AD-24) -------------------------------


def test_step_status_rejected_yields_failed(db, _clean_ack_dir):
    """rejected Acknowledgement → terminal='Failed' (Story 2.7 full logic).

    Story 2.8: the resolver reads Acknowledgements from the disk-backed
    store, not from a hand-rolled SQL table. The test writes via
    `acknowledgement_store.write` and asserts `step_status` returns
    `Failed`.
    """
    from harness.acknowledgement_store import write, ArtifactRef
    write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="rejected",
        artifact_ref=ArtifactRef(
            step="design", project_id="p1", run_id="R1", hash="sha256:" + "0" * 64
        ),
        rejection_reason="missing AC-7",
    )
    status = step_status(db, "p1", "R1", "design")
    assert status.terminal == "Failed"
    assert status.gate_mode == "enforced"


def test_step_status_accepted_yields_locked(db, _clean_ack_dir):
    """accepted Acknowledgement → terminal='Locked'."""
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
    assert status.terminal == "Locked"


def test_step_status_trivial_yields_done(db, _clean_ack_dir):
    """trivial tier + no Acknowledgement → Done/skipped."""
    status = step_status(db, "p1", "R1", "research", project_size="trivial")
    assert status.terminal == "Done"
    assert status.gate_mode == "skipped"


def test_step_status_epic_no_ack_yields_pending(db, _clean_ack_dir):
    """epic tier + no Acknowledgement → Pending/enforced."""
    status = step_status(db, "p1", "R1", "research", project_size="epic")
    assert status.terminal == "Pending"
    assert status.gate_mode == "enforced"


def test_step_status_acknowledgements_table_absent_yields_pending(
    db, _clean_ack_dir
):
    """No `acknowledgements/` directory → Pending (tolerated).

    Story 2.8: the resolver reads from the file system. An absent
    `acknowledgements/p1/R1/research/` directory is the equivalent of
    the previous "no table" path — `read_latest` returns None and the
    resolver falls through to `Pending`.
    """
    status = step_status(db, "p1", "R1", "research")
    assert status.terminal == "Pending"


# --- AC: gate_mode_for (FR-12) ------------------------------------------


def test_gate_mode_for_trivial_returns_skipped():
    assert gate_mode_for("trivial") == "skipped"


def test_gate_mode_for_session_returns_skipped():
    assert gate_mode_for("session") == "skipped"


def test_gate_mode_for_epic_returns_enforced():
    assert gate_mode_for("epic") == "enforced"


def test_gate_mode_for_project_returns_enforced():
    assert gate_mode_for("project") == "enforced"

