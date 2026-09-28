"""HumanExecutorAdapter — the operator as a runtime executor.

AD-10's `start(capability) / cancel(id) / status(id)` contract, implemented
with the simplest possible v1 UI: a blocking `input()` prompt per capability.
The Workflow Controller treats this adapter like any other executor; the
caller's session supplies the operator's response.

Synchronous + blocking by design for v1 (single-node self-hosted per
PRD §6.2). v2 may swap `input()` for a non-blocking prompt and add a `poll`
method; the public surface of `HumanAdapter` will not change.
"""

from __future__ import annotations

from typing import Any

from harness.executor import AdapterOutcome, AuthMode, validate_manifest


class HumanAdapter:
    """Operator-as-adapter. Constructed with no args; one instance is shared
    across the registry (the adapter is stateless).
    """

    SUPPORTED_CAPABILITIES = (
        "research",
        "design",
        "coding",
        "testing",
        "review",
        "delivery",
    )
    AUTH_MODE: AuthMode = "human"

    def __init__(self) -> None:
        self._last_outcome: AdapterOutcome | None = None

    # --- Public API --------------------------------------------------------

    def start(self, capability: str) -> AdapterOutcome:
        """Block on input() and return the operator's response as an AdapterOutcome."""
        if capability not in self.SUPPORTED_CAPABILITIES:
            outcome = AdapterOutcome(
                status="failed",
                payload={
                    "error": f"capability_not_supported: {capability}",
                    "supported": list(self.SUPPORTED_CAPABILITIES),
                },
            )
            self._last_outcome = outcome
            return outcome
        prompt = f"[harness/human] capability={capability} — operator input: "
        try:
            operator_input = input(prompt)
        except EOFError:
            outcome = AdapterOutcome(
                status="failed",
                payload={"error": "operator_input_eof"},
            )
            self._last_outcome = outcome
            return outcome
        outcome = AdapterOutcome(
            status="succeeded",
            payload={"capability": capability, "operator_input": operator_input},
        )
        self._last_outcome = outcome
        return outcome

    def cancel(self, invocation_id: str) -> None:
        # No-op: the human adapter is driven by an interactive prompt, not
        # by an async work loop. Calling cancel signals "operator changed
        # their mind" but the next start() call already has a fresh prompt.
        return None

    def status(self, invocation_id: str) -> AdapterOutcome | None:
        return self._last_outcome

    # --- Helpers -----------------------------------------------------------

    @staticmethod
    def manifest() -> dict[str, Any]:
        """The manifest this adapter would declare at registration. Static;
        the registry reads this when registering on boot."""
        return {
            "name": "human",
            "auth_mode": HumanAdapter.AUTH_MODE,
            "capabilities": list(HumanAdapter.SUPPORTED_CAPABILITIES),
            "description": "Operator-as-adapter: blocks on input() for capability prompts.",
        }


# Re-export for the validate_manifest test below; not part of the public API.
__all__ = ["HumanAdapter", "SUPPORTED_CAPABILITIES"]
# Re-bind the constant name for the test's convenience import.
SUPPORTED_CAPABILITIES = HumanAdapter.SUPPORTED_CAPABILITIES
