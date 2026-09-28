"""Tests for harness.executor (AdapterRegistry + manifest validation).

The `fresh_registry` autouse fixture replaces ADAPTER_REGISTRY with an empty
AdapterRegistry and re-runs the boot-time `_register_human()` call so every
test starts with `["human"]` registered. Individual tests then exercise
register/list/get paths without re-registering the human adapter.
"""

from __future__ import annotations

import pytest

from harness import executor as harness_executor
from harness.executor import (
    ADAPTER_REGISTRY,
    AdapterManifest,
    AdapterRegistry,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Replace ADAPTER_REGISTRY with a fresh empty one + re-register human."""
    harness_executor.ADAPTER_REGISTRY = AdapterRegistry()
    harness_executor._register_human()
    yield
    # Restore: also start fresh, with human registered, for subsequent test files.
    harness_executor.ADAPTER_REGISTRY = AdapterRegistry()
    harness_executor._register_human()


# AC 1: fresh registry after fixture → list = ["human"]
def test_registry_list_after_human_registered():
    assert ADAPTER_REGISTRY.list() == ["human"]


# AC 2: human start with patched input → succeeded + payload
def test_human_start_returns_succeeded_outcome(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "ok")
    result = ADAPTER_REGISTRY.get("human").start("review")
    assert result["status"] == "succeeded"
    assert result["payload"]["operator_input"] == "ok"
    assert result["payload"]["capability"] == "review"


# AC 3: status returns cached outcome
def test_human_status_returns_cached_outcome(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "looks good")
    ADAPTER_REGISTRY.get("human").start("review")
    cached = ADAPTER_REGISTRY.get("human").status("review")
    assert cached is not None
    assert cached["status"] == "succeeded"
    assert cached["payload"]["operator_input"] == "looks good"


# AC 4: human cancel is no-op
def test_human_cancel_is_noop():
    assert ADAPTER_REGISTRY.get("human").cancel("any-id") is None


# AC 5: empty name → invalid_manifest_name
def test_register_empty_name_raises_invalid_name():
    with pytest.raises(ValueError, match="invalid_manifest_name"):
        ADAPTER_REGISTRY.register(
            object(),
            AdapterManifest(name="", auth_mode="bearer", capabilities=["x"]),  # type: ignore[arg-type]
        )


# AC 6: unknown auth_mode → invalid_manifest_auth_mode
def test_register_unknown_auth_mode_raises():
    with pytest.raises(ValueError, match="invalid_manifest_auth_mode"):
        ADAPTER_REGISTRY.register(
            object(),
            AdapterManifest(name="x", auth_mode="magic", capabilities=["x"]),  # type: ignore[arg-type]
        )


# AC 7: empty capabilities → invalid_manifest_capabilities
def test_register_empty_capabilities_raises():
    with pytest.raises(ValueError, match="invalid_manifest_capabilities"):
        ADAPTER_REGISTRY.register(
            object(),
            AdapterManifest(name="x", auth_mode="bearer", capabilities=[]),  # type: ignore[arg-type]
        )


# AC 8: duplicate name → adapter_already_registered (try registering "human" again)
def test_register_duplicate_name_raises():
    with pytest.raises(ValueError, match="adapter_already_registered"):
        ADAPTER_REGISTRY.register(object(), HumanAdapter.manifest())


# Helper inside the test module so AC 8 can reuse the human manifest.
from harness.adapters.human import HumanAdapter  # noqa: E402


# AC 9: capability not supported → AdapterOutcome(status="failed")
def test_human_capability_not_supported():
    result = ADAPTER_REGISTRY.get("human").start("non-existent-capability")
    assert result["status"] == "failed"
    assert "capability_not_supported" in result["payload"]["error"]
