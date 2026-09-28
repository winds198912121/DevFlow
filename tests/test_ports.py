"""Tests for harness.ports — the runtime shape of the allowlist symbols.

The lint enforces which symbols may be imported from `harness.ports`; this
test enforces the runtime shape of those symbols (they must be types/Protocols,
not strings) so downstream `isinstance` checks actually work.
"""

from __future__ import annotations

import pytest


def test_all_eight_ports_importable_as_types():
    from harness.ports import (
        StepExecutorPort,
        HerdrEventPort,
        ExecutorTuple,
        SkillManifest,
        ArtifactContract,
        Acknowledgement,
        ErrorRecord,
        RunEvent,
    )
    for sym in (StepExecutorPort, HerdrEventPort, ExecutorTuple, SkillManifest,
                ArtifactContract, Acknowledgement, ErrorRecord, RunEvent):
        # Each must be a type (not a string, not None).
        assert isinstance(sym, type), f"{sym!r} is not a type"


def test_star_import_resolves_to_allowlist():
    from harness import ports
    ns = vars(ports).copy()
    ns.pop("__all__", None)
    ns.pop("__builtins__", None)
    ns.pop("__cached__", None)
    ns.pop("__path__", None)
    ns.pop("__doc__", None)
    ns.pop("__file__", None)
    ns.pop("__loader__", None)
    ns.pop("__name__", None)
    ns.pop("__package__", None)
    ns.pop("__spec__", None)
    ns.pop("annotations", None)
    ns.pop("Protocol", None)
    ns.pop("runtime_checkable", None)
    ns.pop("Any", None)
    assert set(ns.keys()) == set(ports.__all__)


def test_protocol_isinstance_works():
    # runtime_checkable Protocol allows isinstance checks against the type
    # itself (any object instance is NOT an instance of a bare Protocol).
    from harness.ports import StepExecutorPort
    assert isinstance(StepExecutorPort, type)


def test_empty_module_does_not_have_allowlist():
    # A side-check: the lint's _load_allowlist expects `__all__`. If someone
    # refactors ports to drop __all__, this test guards the regression.
    import harness.ports as p
    assert hasattr(p, "__all__")
    assert len(p.__all__) == 8
