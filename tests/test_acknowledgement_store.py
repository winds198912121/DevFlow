"""Tests for harness.acknowledgement_store (Story 2.8).

See the plan's I/O Matrix in the epic-pipeline-and-gates folder.
"""

from __future__ import annotations

import shutil

import pytest

from harness.acknowledgement_store import (
    ACKNOWLEDGEMENTS_DIR,
    AcknowledgementAlreadyExists,
    AcknowledgementPathMismatch,
    AcknowledgementStoreError,
    AcknowledgementUnsigned,
    ArtifactRef,
    OpenItem,
    list_for,
    read,
    read_latest,
    validate_verdict,
    write,
)


# --- Autouse fixture: clean Acknowledgements dir ----------------------------


@pytest.fixture(autouse=True)
def _clean_ack_dir():
    """Wipe `acknowledgements/` between tests so writes don't leak across."""
    yield
    if ACKNOWLEDGEMENTS_DIR.exists():
        shutil.rmtree(ACKNOWLEDGEMENTS_DIR)


# --- Helpers --------------------------------------------------------------


def _artifact_ref(step: str = "design", run_id: str = "R1") -> ArtifactRef:
    """A valid ArtifactRef with a sha256: 64-hex hash."""
    return ArtifactRef(
        step=step,
        project_id="p1",
        run_id=run_id,
        hash="sha256:" + "0" * 64,
    )


# --- AC: Verdict enum enforced at write time ------------------------------


def test_validate_verdict_accepts_all_three_ad12_values():
    for v in ("accepted", "accepted-with-open-items", "rejected"):
        validate_verdict(v)


def test_validate_verdict_rejects_unknown_value():
    with pytest.raises(ValueError, match="verdict_invalid"):
        validate_verdict("approved")


def test_write_with_invalid_verdict_raises_before_signing():
    """`write` refuses 'approved' BEFORE signing or writing."""
    with pytest.raises(ValueError, match="verdict_invalid"):
        write(
            project_id="p1",
            run_id="R1",
            step="design",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="approved",
            artifact_ref=_artifact_ref(),
        )


# --- AC: verdict-specific required fields ---------------------------------


def test_accepted_with_open_items_requires_open_items():
    with pytest.raises(AcknowledgementStoreError, match="open_items_required"):
        write(
            project_id="p1",
            run_id="R1",
            step="review",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="accepted-with-open-items",
            artifact_ref=_artifact_ref(step="review"),
            # open_items missing
        )


def test_rejected_requires_rejection_reason():
    with pytest.raises(AcknowledgementStoreError, match="rejection_reason"):
        write(
            project_id="p1",
            run_id="R1",
            step="design",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="rejected",
            artifact_ref=_artifact_ref(),
        )


# --- AC: artifact_ref triple matches write arguments -----------------------


def test_artifact_ref_path_mismatch_raises():
    """artifact_ref's triple must match the write args."""
    with pytest.raises(AcknowledgementStoreError, match="path_mismatch"):
        write(
            project_id="p1",
            run_id="R1",
            step="design",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="accepted",
            artifact_ref=ArtifactRef(
                step="design",
                project_id="p2",  # mismatch
                run_id="R1",
                hash="sha256:" + "0" * 64,
            ),
        )


# --- AC: step must be in STEP_ORDER ----------------------------------------


def test_write_with_unknown_step_raises():
    with pytest.raises(AcknowledgementStoreError, match="unknown_step"):
        write(
            project_id="p1",
            run_id="R1",
            step="ghosts",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="accepted",
            artifact_ref=_artifact_ref(step="ghosts"),
        )


# --- AC: write + read roundtrip -------------------------------------------


def test_write_then_read_roundtrip():
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    read_back = read(
        record.acknowledgement_id,
        project_id="p1",
        run_id="R1",
        step="design",
    )
    assert read_back == record
    assert read_back.verdict == "accepted"
    assert read_back.acknowledgement_id == record.acknowledgement_id


def test_signature_is_64_bytes_ed25519():
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    assert isinstance(record.signature, bytes)
    assert len(record.signature) == 64


# --- AC: AD-23 path-triple signature coverage -----------------------------


def test_ad23_path_mismatch_raises():
    """A record whose body claims project_id=P2 but file lives under P1
    raises AcknowledgementPathMismatch on read."""
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    # Caller passes the WRONG path triple (claims P2 but the file is under P1).
    with pytest.raises(AcknowledgementPathMismatch):
        read(
            record.acknowledgement_id,
            project_id="p2",  # mismatch
            run_id="R1",
            step="design",
        )


# --- AC: tampered signature → AcknowledgementUnsigned ---------------------


def test_tampered_signature_raises_acknowledgement_unsigned():
    """Flip the signature field on disk; raises AcknowledgementUnsigned."""
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    path = (
        ACKNOWLEDGEMENTS_DIR / "p1" / "R1" / "design"
        / f"{record.acknowledgement_id}.json"
    )
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    # Flip one byte in the signature.
    sig_bytes = bytearray(bytes.fromhex(data["signature"]))
    sig_bytes[0] ^= 0xFF
    data["signature"] = sig_bytes.hex()
    path.write_text(__import__("json").dumps(data), encoding="utf-8")

    with pytest.raises(AcknowledgementUnsigned):
        read(
            record.acknowledgement_id,
            project_id="p1",
            run_id="R1",
            step="design",
        )


def test_body_mutation_invalidates_signature():
    """Edit the verdict on disk; read raises AcknowledgementUnsigned."""
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    path = (
        ACKNOWLEDGEMENTS_DIR / "p1" / "R1" / "design"
        / f"{record.acknowledgement_id}.json"
    )
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    data["verdict"] = "rejected"
    path.write_text(__import__("json").dumps(data), encoding="utf-8")

    with pytest.raises(AcknowledgementUnsigned):
        read(
            record.acknowledgement_id,
            project_id="p1",
            run_id="R1",
            step="design",
        )


# --- AC: read_latest + list_for ------------------------------------------


def test_read_latest_returns_none_for_unknown_step():
    assert read_latest("p1", "R1", "design") is None


def test_read_latest_returns_most_recent():
    """Two Acknowledgements: read_latest returns the lexicographically-
    last ULID (chronological)."""
    write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="first",
        acknowledger_kind="check",
        verdict="rejected",
        artifact_ref=_artifact_ref(),
        rejection_reason="first attempt",
    )
    second = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="second",
        acknowledger_kind="check",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    latest = read_latest("p1", "R1", "design")
    assert latest is not None
    assert latest.acknowledgement_id == second.acknowledgement_id


def test_list_for_returns_all_records_sorted():
    import time
    a = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="a",
        acknowledger_kind="check",
        verdict="rejected",
        artifact_ref=_artifact_ref(),
        rejection_reason="x",
    )
    # ULIDs are millisecond-monotonic; a 2-ms gap ensures b's ULID sorts
    # strictly after a's even under monotonic-counter semantics.
    time.sleep(0.002)
    b = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="b",
        acknowledger_kind="check",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    records = list_for("p1", "R1", "design")
    assert len(records) == 2
    assert records[0].acknowledgement_id == a.acknowledgement_id
    assert records[1].acknowledgement_id == b.acknowledgement_id


# --- AC: read of missing file --------------------------------------------


def test_read_missing_file_raises():
    with pytest.raises(AcknowledgementStoreError, match="not_found"):
        read("NONEXISTENT", project_id="p1", run_id="R1", step="design")


# --- AC: duplicate ULID collision ------------------------------------------


def test_write_duplicate_ulid_raises_already_exists(monkeypatch):
    """Forcing two writes to produce the same ULID triggers AcknowledgementAlreadyExists.

    Patches `harness.acknowledgement_store.ulid.ULID.from_datetime` to
    return a fixed value so both `write` calls land on the same
    filesystem path. The writer must refuse to overwrite.
    """
    import harness.acknowledgement_store as ack_store
    fixed_ulid = ack_store.ulid.ULID()
    monkeypatch.setattr(ack_store.ulid.ULID, "from_datetime", lambda dt: fixed_ulid)

    write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="first",
        acknowledger_kind="check",
        verdict="rejected",
        artifact_ref=_artifact_ref(),
        rejection_reason="first attempt",
    )
    with pytest.raises(AcknowledgementAlreadyExists):
        write(
            project_id="p1",
            run_id="R1",
            step="design",
            acknowledger="second",
            acknowledger_kind="check",
            verdict="accepted",
            artifact_ref=_artifact_ref(),
        )


# --- AC: real cross-project forgery (file copied to a different project dir)


def test_cross_project_copy_forgery_raises_path_mismatch(tmp_path):
    """The actual AD-23 attack: copy a signed Acknowledgement to a
    different project's directory and try to read it under the new
    project_id. The body still claims the original project, so the
    body-vs-call path-triple mismatch raises AcknowledgementPathMismatch.
    """
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    # Copy the file from p1 to p2 — the file's body still claims p1.
    import shutil
    src = (
        ACKNOWLEDGEMENTS_DIR / "p1" / "R1" / "design"
        / f"{record.acknowledgement_id}.json"
    )
    dst = (
        ACKNOWLEDGEMENTS_DIR / "p2" / "R1" / "design"
        / f"{record.acknowledgement_id}.json"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)

    # Read under the wrong project_id — body claims p1, call claims p2
    # → AcknowledgementPathMismatch.
    with pytest.raises(AcknowledgementPathMismatch):
        read(
            record.acknowledgement_id,
            project_id="p2",
            run_id="R1",
            step="design",
        )

    # Reading under the original project_id still works (file + body match).
    read_back = read(
        record.acknowledgement_id,
        project_id="p1",
        run_id="R1",
        step="design",
    )
    assert read_back == record


# --- AC: from_file_dict missing required field raises structured error ----


def test_from_file_dict_missing_field_raises():
    """A file missing a required field (e.g. 'verdict') raises
    AcknowledgementStoreError, not raw KeyError. This is what the
    dashboard (Story 4.x) sees if a record is hand-edited to drop a
    field — the dashboard must surface the structured error rather than
    crash on a KeyError that escapes the AcknowledgementStoreError
    boundary.
    """
    # Write a valid record first so the file exists.
    record = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="mei@team",
        acknowledger_kind="human",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    # Corrupt: drop the `verdict` field.
    path = (
        ACKNOWLEDGEMENTS_DIR / "p1" / "R1" / "design"
        / f"{record.acknowledgement_id}.json"
    )
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    del data["verdict"]
    path.write_text(__import__("json").dumps(data), encoding="utf-8")

    with pytest.raises(AcknowledgementStoreError):
        read(
            record.acknowledgement_id,
            project_id="p1",
            run_id="R1",
            step="design",
        )


# --- AC: list_for tolerates a corrupted record -----------------------------


def test_list_for_skips_corrupted_records(monkeypatch):
    """A tampered Acknowledgement file in the step dir is skipped by
    list_for (with a warning), not propagated as an exception. The
    dashboard reads list_for; a single corrupted record must not crash
    the whole listing.
    """
    a = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="a",
        acknowledger_kind="check",
        verdict="rejected",
        artifact_ref=_artifact_ref(),
        rejection_reason="x",
    )
    b = write(
        project_id="p1",
        run_id="R1",
        step="design",
        acknowledger="b",
        acknowledger_kind="check",
        verdict="accepted",
        artifact_ref=_artifact_ref(),
    )
    # Corrupt the first file.
    src_a = (
        ACKNOWLEDGEMENTS_DIR / "p1" / "R1" / "design" / f"{a.acknowledgement_id}.json"
    )
    src_a.write_text("{not valid json", encoding="utf-8")

    with pytest.warns(UserWarning, match="acknowledgement_skipped"):
        records = list_for("p1", "R1", "design")
    # The corrupted one is skipped; the valid one is returned.
    assert len(records) == 1
    assert records[0].acknowledgement_id == b.acknowledgement_id


# --- AC: path traversal in identifiers rejected at write ------------------


def test_write_with_traversal_segment_raises():
    """A `project_id="../../etc"` must be rejected before any file write
    (path-traversal hardening; the harness is single-process CLI but
    defense-in-depth matters)."""
    with pytest.raises(AcknowledgementStoreError, match="project_id_invalid"):
        write(
            project_id="../../etc",
            run_id="R1",
            step="design",
            acknowledger="mei@team",
            acknowledger_kind="human",
            verdict="accepted",
            artifact_ref=ArtifactRef(
                step="design",
                project_id="../../etc",
                run_id="R1",
                hash="sha256:" + "0" * 64,
            ),
        )


# --- AC: OpenItem validation ----------------------------------------------


def test_open_item_id_invalid_raises():
    with pytest.raises(ValueError, match="open_item.id_invalid"):
        OpenItem(id="bad id with spaces", description="x")


def test_open_item_description_required():
    with pytest.raises(ValueError, match="open_item.description_required"):
        OpenItem(id="OI-1", description="")


