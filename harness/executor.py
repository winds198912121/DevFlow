"""ExecutorAdapter port — runtime seam between Workflow Controller and Agent runtimes.

AD-10: each Agent adapter (Pi / OMP / Codex / Claude Code / DSH / human)
declares an AdapterManifest and registers itself with the module-level
ADAPTER_REGISTRY singleton. The Workflow Controller resolves a step's
executor tuple via `ADAPTER_REGISTRY.get(adapter_name)` and invokes the
returned adapter's `start(capability)`, `cancel(id)`, `status(id)` per
the StepExecutorPort protocol in `harness.ports`.

The `human` adapter is registered at module-import time so every v1 boot
has at least one usable executor. Future concrete adapters (Pi, OMP, Codex)
register themselves when their module is imported; the operator opts in
to each adapter by importing its module.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


# --- TypedDicts --------------------------------------------------------------

AuthMode = Literal["bearer", "oauth", "cli-resident", "human"]


class AdapterManifest(TypedDict, total=False):
    """The shape an adapter declares at registration time (AD-10d).

    Required: name, auth_mode, capabilities.
    Optional: description.
    """

    name: str
    auth_mode: AuthMode
    capabilities: list[str]
    description: NotRequired[str]


class AdapterOutcome(TypedDict, total=False):
    """The shape an adapter's start() returns.

    status: "succeeded" | "failed" | "cancelled"
    payload: optional dict with capability-specific results (or an `error` key on failure)
    """

    status: Literal["succeeded", "failed", "cancelled"]
    payload: NotRequired[dict[str, Any]]


# --- Exceptions -------------------------------------------------------------


class _ManifestError(ValueError):
    """Base for all manifest validation errors. All carry a fixed prefix so
    callers can pattern-match the failure category.
    """


def invalid_manifest_name(detail: str) -> _ManifestError:
    return _ManifestError(f"invalid_manifest_name: {detail}")


def invalid_manifest_auth_mode(detail: str) -> _ManifestError:
    return _ManifestError(f"invalid_manifest_auth_mode: {detail}")


def invalid_manifest_capabilities(detail: str) -> _ManifestError:
    return _ManifestError(f"invalid_manifest_capabilities: {detail}")


def adapter_already_registered(detail: str) -> _ManifestError:
    return _ManifestError(f"adapter_already_registered: {detail}")


# --- Registry ---------------------------------------------------------------


_VALID_AUTH_MODES = ("bearer", "oauth", "cli-resident", "human")


def validate_manifest(manifest: AdapterManifest) -> None:
    """Raise _ManifestError on the first defect; raise nothing on a clean manifest."""
    if not isinstance(manifest, dict):
        raise invalid_manifest_name(f"manifest must be a dict, got {type(manifest).__name__}")
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        raise invalid_manifest_name(f"name must be a non-empty string, got {name!r}")
    auth_mode = manifest.get("auth_mode")
    if auth_mode not in _VALID_AUTH_MODES:
        raise invalid_manifest_auth_mode(
            f"auth_mode must be one of {_VALID_AUTH_MODES}, got {auth_mode!r}"
        )
    caps = manifest.get("capabilities")
    if not isinstance(caps, list) or not caps:
        raise invalid_manifest_capabilities(
            "capabilities must be a non-empty list of strings"
        )
    if not all(isinstance(c, str) and c.strip() for c in caps):
        raise invalid_manifest_capabilities(
            "capabilities entries must be non-empty strings"
        )


class AdapterRegistry:
    """Ordered singleton holding all registered executor adapters.

    Sole writer pattern (mirrors AD-4 / AD-22): every registration goes
    through `register()`, which validates the manifest and rejects
    duplicates / malformed entries before the adapter lands in the store.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}
        self._manifests: dict[str, AdapterManifest] = {}

    def register(self, adapter: Any, manifest: AdapterManifest) -> None:
        validate_manifest(manifest)
        name = manifest["name"]
        if name in self._adapters:
            raise adapter_already_registered(name)
        self._adapters[name] = adapter
        self._manifests[name] = dict(manifest)

    def unregister(self, name: str) -> None:
        self._adapters.pop(name, None)
        self._manifests.pop(name, None)

    def list(self) -> list[str]:
        """Return registered adapter names in registration order (Python 3.7+ dict)."""
        return list(self._adapters.keys())

    def get(self, name: str) -> Any:
        """Return the registered adapter or raise KeyError."""
        return self._adapters[name]

    def manifest(self, name: str) -> AdapterManifest | None:
        """Return the manifest for `name`, or None if unregistered."""
        m = self._manifests.get(name)
        return dict(m) if m is not None else None


# Module-level singleton — every consumer imports this name.
ADAPTER_REGISTRY = AdapterRegistry()


# --- Boot-time registration of the human adapter ---------------------------
#
# The human adapter is required for v1 (every project needs at least one
# executor). The import is unconditional: if `harness.adapters.human` is
# missing, that's a real bug we want to surface, not swallow.

def _register_human() -> None:
    from harness.adapters.human import HumanAdapter
    if "human" in ADAPTER_REGISTRY.list():
        return  # idempotent across multiple imports
    ADAPTER_REGISTRY.register(
        HumanAdapter(),
        HumanAdapter.manifest(),
    )


_register_human()
