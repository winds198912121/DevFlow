"""Published-port allowlist — the one `harness.*` surface the four layer roots
(skills/, agents/, herdr/, dashboard/) may import.

AD-26: every import under skills/, agents/, herdr/, dashboard/ whose module
path begins with `harness.` is rejected by `tools/check_layer_boundaries.py`
unless the imported symbol is listed in this module's `__all__`. Concrete
implementations land in later stories; this module declares the type stubs
under TYPE_CHECKING so a runtime `from harness.ports import StepExecutorPort`
succeeds and a static type checker (mypy / pyright) sees the Protocol shape.

The allowlist `__all__` is what the lint reads — not the runtime-importable
symbols — so a stub here continues to authorize the import even before the
concrete type lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    class StepExecutorPort(Protocol):
        """Adapter contract for executor invocation (AD-10)."""

        def start(self, capability: str) -> Any: ...
        def cancel(self, invocation_id: str) -> None: ...
        def status(self, invocation_id: str) -> Any: ...

    class HerdrEventPort(Protocol):
        """Observer interface for Herdr events (AD-9, AD-19)."""

        def emit(self, event: dict) -> None: ...

    class ExecutorTuple(Protocol):
        """The (agent, model, skills[]) tuple named in FR-5."""

        agent: str
        model: str
        skills: tuple[str, ...]

    class SkillManifest(Protocol):
        """Pinned Skill descriptor (FR-6, AD-6)."""

        name: str
        version: str

    class ArtifactContract(Protocol):
        """Schema reference for a step's input/output (FR-3, AD-27)."""

        name: str
        version: str
        schema_path: str

    class Acknowledgement(Protocol):
        """Gate Acknowledgement record (FR-10, AD-5, PRD A8)."""

        acknowledger: str
        timestamp: str
        verdict: str

    class ErrorRecord(Protocol):
        """Append-only error store record (FR-13, AD-4, PRD addendum §5)."""

        record_id: str
        category: str

    class RunEvent(Protocol):
        """Run Event Log entry (NFR-Obs-1, AD-14)."""

        event_id: str
        project_id: str
        run_id: str
        step: str

# The runtime symbol that downstream code imports. CI lint reads this list,
# not the TYPE_CHECKING block.
StepExecutorPort = "StepExecutorPort"
HerdrEventPort = "HerdrEventPort"
ExecutorTuple = "ExecutorTuple"
SkillManifest = "SkillManifest"
ArtifactContract = "ArtifactContract"
Acknowledgement = "Acknowledgement"
ErrorRecord = "ErrorRecord"
RunEvent = "RunEvent"

__all__ = [
    "StepExecutorPort",
    "HerdrEventPort",
    "ExecutorTuple",
    "SkillManifest",
    "ArtifactContract",
    "Acknowledgement",
    "ErrorRecord",
    "RunEvent",
]
