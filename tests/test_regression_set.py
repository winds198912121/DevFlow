"""Tests for harness.regression_set (Story 3.4)."""

from __future__ import annotations

import pytest

from harness.regression_set import (
    DEFAULT_DB,
    BenchInsufficient,
    NonComparableSet,
    RegressionSetRemoveRequiresReason,
    add,
    bench_query,
    remove,
)


@pytest.fixture(autouse=True)
def _clean_db():
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_DB.with_suffix(ext)
        if p.exists():
            p.unlink()
    yield
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_DB.with_suffix(ext)
        if p.exists():
            p.unlink()


def test_add_then_bench_query_returns_recommendation():
    for i in range(3):
        add(
            f"R{i}",
            step="coding",
            project_size_tier="trivial",
            artifact_contract_version="v1",
            metric_value=0.95 + i * 0.01,
            metric_definition="fr_passed/fr_total",
            added_by="cli",
        )
    rec = bench_query("coding", "trivial", "v1", k=3)
    assert len(rec.contributing_runs) == 3
    assert 0.95 <= rec.metric_summary <= 0.97


def test_bench_query_with_k_minus_one_raises_insufficient():
    for i in range(2):
        add(
            f"R{i}",
            step="coding",
            project_size_tier="trivial",
            artifact_contract_version="v1",
            metric_value=0.9,
            metric_definition="fr_passed/fr_total",
            added_by="cli",
        )
    with pytest.raises(BenchInsufficient):
        bench_query("coding", "trivial", "v1", k=3)


def test_add_same_id_is_noop():
    add("R1", step="coding", project_size_tier="trivial",
        artifact_contract_version="v1", metric_value=0.9,
        metric_definition="x", added_by="cli")
    add("R1", step="coding", project_size_tier="trivial",
        artifact_contract_version="v1", metric_value=0.5,
        metric_definition="y", added_by="cli")
    rec = bench_query("coding", "trivial", "v1", k=1)
    assert rec.metric_summary == 0.9  # first value wins


def test_bench_mixed_contracts_raises_non_comparable():
    add("R1", step="coding", project_size_tier="trivial",
        artifact_contract_version="v1", metric_value=0.9,
        metric_definition="x", added_by="cli")
    add("R2", step="coding", project_size_tier="trivial",
        artifact_contract_version="v2", metric_value=0.5,
        metric_definition="x", added_by="cli")
    with pytest.raises(NonComparableSet):
        bench_query("coding", "trivial")


def test_remove_requires_reason():
    add("R1", step="coding", project_size_tier="trivial",
        artifact_contract_version="v1", metric_value=0.9,
        metric_definition="x", added_by="cli")
    with pytest.raises(RegressionSetRemoveRequiresReason):
        remove("R1")


def test_remove_with_reason_tombstones_and_drops_below_k():
    for i in range(3):
        add(
            f"R{i}",
            step="coding",
            project_size_tier="trivial",
            artifact_contract_version="v1",
            metric_value=0.9,
            metric_definition="x",
            added_by="cli",
        )
    assert remove("R1", reason="bad data", removed_by="ops") is True
    with pytest.raises(BenchInsufficient):
        bench_query("coding", "trivial", "v1", k=3)


def test_bench_mixed_metric_definitions_raise_non_comparable():
    """A cell mixing metric definitions must refuse, not average.

    Regression: `bench_query` took `metric_definition` from the first row while
    averaging *every* row, so a cell holding runs measured two different ways
    produced a number that was not a metric, labelled with whichever definition
    happened to sort first. The contract axis was already guarded; the metric
    axis was not, despite the comment claiming it was.
    """
    for i, definition in enumerate(["fr_passed/fr_total", "pass_rate", "fr_passed/fr_total"]):
        add(
            f"R{i}",
            step="coding",
            project_size_tier="trivial",
            artifact_contract_version="v1",
            metric_value=0.9,
            metric_definition=definition,
            added_by="cli",
        )
    with pytest.raises(NonComparableSet):
        bench_query("coding", "trivial", "v1", k=1)
    # The same holds when the caller omits the contract and the set is
    # otherwise uniform.
    with pytest.raises(NonComparableSet):
        bench_query("coding", "trivial", k=1)


def test_bench_uniform_metric_definitions_still_average():
    """The guard must not reject a well-formed cell."""
    for i in range(3):
        add(
            f"R{i}",
            step="coding",
            project_size_tier="trivial",
            artifact_contract_version="v1",
            metric_value=0.9 + i / 100,
            metric_definition="fr_passed/fr_total",
            added_by="cli",
        )
    rec = bench_query("coding", "trivial", "v1", k=3)
    assert rec.metric_definition == "fr_passed/fr_total"
    assert rec.metric_summary == pytest.approx((0.9 + 0.91 + 0.92) / 3)
