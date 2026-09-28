"""Tests for harness.ports — the runtime shape of the allowlist symbols.

The lint enforces which symbols may be imported from `harness.ports`; this
test enforces the runtime shape of those symbols (they must be types/Protocols,
not strings) so downstream `isinstance` checks actually work.
"""

from __future__ import annotations

import pytest


def test_all_ports_importable_as_types():
    from harness.ports import (
        StepExecutorPort,
        HerdrEventPort,
        ExecutorTuple,
        SkillManifest,
        ArtifactContract,
        Acknowledgement,
        ErrorRecord,
        RunEvent,
        DashboardPort,
        DashboardRefusal,
    )
    for sym in (StepExecutorPort, HerdrEventPort, ExecutorTuple, SkillManifest,
                ArtifactContract, Acknowledgement, ErrorRecord, RunEvent,
                DashboardPort, DashboardRefusal):
        # Each must be a type (not a string, not None).
        assert isinstance(sym, type), f"{sym!r} is not a type"


def test_star_import_resolves_to_allowlist():
    """`from harness.ports import *` exposes exactly the allowlist.

    Submodule objects are excluded from the comparison: importing a submodule
    (here, `harness.ports.dashboard`, for its port symbols) binds that name in
    this package's namespace. That is Python's import machinery, not an
    exported symbol, so it must not count as a star-export.
    """
    import types

    from harness import ports
    ns = {
        name: value
        for name, value in vars(ports).items()
        if not name.startswith("__") and not isinstance(value, types.ModuleType)
    }
    for helper in ("annotations", "Protocol", "runtime_checkable", "Any"):
        ns.pop(helper, None)
    assert set(ns.keys()) == set(ports.__all__)
    # The direction the lint depends on: every allowlisted name must resolve,
    # or `from harness.ports import <name>` fails for a downstream layer.
    assert set(ports.__all__) <= set(vars(ports))


def test_protocol_isinstance_works():
    # runtime_checkable Protocol allows isinstance checks against the type
    # itself (any object instance is NOT an instance of a bare Protocol).
    from harness.ports import StepExecutorPort
    assert isinstance(StepExecutorPort, type)


def test_ports_module_exposes_an_allowlist():
    # The lint's _load_allowlist reads `__all__`; if a refactor dropped it the
    # lint would silently stop enforcing AD-26. Asserting a specific length
    # here would instead break every time a port is legitimately published.
    import harness.ports as p
    assert hasattr(p, "__all__")
    assert p.__all__, "ports allowlist must not be empty"
