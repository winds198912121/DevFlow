"""Tests for the HumanAdapter — the default executor registered at boot."""

from __future__ import annotations

import pytest

from harness.adapters.human import HumanAdapter
from harness.executor import AdapterManifest


@pytest.fixture
def adapter() -> HumanAdapter:
    return HumanAdapter()


# Happy path: input returns "ok", capability is supported
def test_start_with_supported_capability_and_input(adapter, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "ok")
    out = adapter.start("coding")
    assert out["status"] == "succeeded"
    assert out["payload"]["operator_input"] == "ok"


# Edge: capability not in SUPPORTED_CAPABILITIES → failed outcome
def test_start_with_unsupported_capability_returns_failed(adapter):
    out = adapter.start("anything-not-supported")
    assert out["status"] == "failed"
    assert "capability_not_supported" in out["payload"]["error"]


# Edge: stdin EOF (input raises EOFError) → failed outcome
def test_start_with_eof_returns_failed(adapter, monkeypatch):
    def fake_input(*_):
        raise EOFError()
    monkeypatch.setattr("builtins.input", fake_input)
    out = adapter.start("coding")
    assert out["status"] == "failed"
    assert out["payload"]["error"] == "operator_input_eof"


# Manifest static helper returns a valid manifest
def test_manifest_static_method():
    m = HumanAdapter.manifest()
    assert m["name"] == "human"
    assert m["auth_mode"] == "human"
    assert set(m["capabilities"]) == set(HumanAdapter.SUPPORTED_CAPABILITIES)
    assert m["description"]


# Coverage: missing adapter raises KeyError from registry.get()
def test_get_unknown_adapter_raises_keyerror():
    from harness.executor import ADAPTER_REGISTRY
    with pytest.raises(KeyError):
        ADAPTER_REGISTRY.get("no-such-adapter")


# Coverage: unregister removes the adapter and its manifest
def test_unregister_removes_adapter_and_manifest():
    from harness.executor import ADAPTER_REGISTRY
    ADAPTER_REGISTRY.register(object(), AdapterManifest(name="temp", auth_mode="bearer", capabilities=["x"]))  # type: ignore[arg-type]
    assert "temp" in ADAPTER_REGISTRY.list()
    assert ADAPTER_REGISTRY.manifest("temp") is not None
    ADAPTER_REGISTRY.unregister("temp")
    assert "temp" not in ADAPTER_REGISTRY.list()
    assert ADAPTER_REGISTRY.manifest("temp") is None
