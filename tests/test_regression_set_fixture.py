"""Tests for the Story 3.8 regression-set fixture."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from harness.regression_set import (
    DEFAULT_DB,
    BenchInsufficient,
    bench_query,
)


_FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures" / "regression-set" / "python-hello-4-runs"
)
_LOADER_PATH = _FIXTURE_DIR / "load.py"


def _load_loader():
    spec = importlib.util.spec_from_file_location(
        "_regression_fixture_loader", _LOADER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_load_adds_four_runs():
    loader = _load_loader()
    added = loader.load()
    assert added == 4


def test_load_is_idempotent():
    loader = _load_loader()
    first = loader.load()
    second = loader.load()
    assert first == 4
    assert second == 0


def test_bench_query_after_load_returns_recommendation():
    loader = _load_loader()
    loader.load()
    rec = bench_query("coding", "trivial", "v1", k=3)
    assert len(rec.contributing_runs) == 4
    assert rec.metric_definition == "fr_passed/fr_total"
    expected_mean = sum([0.92, 0.95, 0.88, 0.91]) / 4
    assert abs(rec.metric_summary - expected_mean) < 1e-9


def test_bench_query_for_unseeded_tier_raises_insufficient():
    _load_loader().load()
    with pytest.raises(BenchInsufficient):
        bench_query("coding", "epic", "v1", k=3)


def test_bench_query_with_k_above_fixture_count_raises_insufficient():
    _load_loader().load()
    with pytest.raises(BenchInsufficient):
        bench_query("coding", "trivial", "v1", k=5)