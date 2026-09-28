#!/usr/bin/env python3
"""CI lint: enforce AD-26 — layer boundary between harness and the four method/execution roots.

Scans every *.py under `skills/`, `agents/`, `herdr/`, `dashboard/`. For each
`import` or `from-import` whose module path begins with `harness.`, the lint
checks that the imported symbol is listed in `harness/ports/__init__.py`'s
`__all__`. Also asserts that each of the four layer roots has a corresponding
`var/<root>/` skeleton directory (treats absence as a violation).

Two path knobs:
  --ports-path  : path to harness/ports/__init__.py (the allowlist source)
  --layer-dir   : parent of the four skills/agents/herdr/dashboard layer roots

Both default to the project root inferred from this script's location, so the
plain `uv run python tools/check_layer_boundaries.py` invocation runs against
the real repo.

Exits 0 on a clean repo, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from tools._lint_helpers import iter_python_files, parse_python_file

DEFAULT_LAYER_ROOTS = ("skills", "agents", "herdr", "dashboard")
DEFAULT_VAR_DIR_NAME = "var"


def _load_allowlist(ports_path: Path) -> tuple[set[str], str | None]:
    """Return (allowed_symbols, error_message). Reads the ports module's
    `__all__` without executing the module body.
    """
    if not ports_path.exists():
        return set(), f"allowlist_unavailable: {ports_path} not found"
    tree_or_error = parse_python_file(ports_path)
    if not isinstance(tree_or_error, ast.Module):
        _, err = tree_or_error
        return set(), f"allowlist_unavailable: {ports_path}:{err}"
    tree = tree_or_error
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if not isinstance(node.value, (ast.List, ast.Tuple)):
                        continue
                    symbols: set[str] = set()
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            symbols.add(elt.value)
                    if not symbols:
                        return set(), f"allowlist_empty: {ports_path}"
                    return symbols, None
    return set(), f"allowlist_empty: {ports_path}"


def _is_harness_module(module: str | None) -> bool:
    return bool(module) and (module == "harness" or module.startswith("harness."))


def _check_import(node: ast.AST, file: Path, allowed: set[str]) -> int:
    """Return count of violations found in this import node."""
    hits = 0
    rel = file.as_posix()
    if isinstance(node, ast.Import):
        for alias in node.names:
            if _is_harness_module(alias.name):
                if alias.name == "harness":
                    print(
                        f"layer_boundary_violation: {rel}:{node.lineno} bare 'harness' import"
                    )
                else:
                    # Whole-module import of a non-allowed harness module.
                    # Currently only harness.ports is allowed; bare `import
                    # harness.ports` is treated as importing the package
                    # wholesale (no symbol binding). Importing the names
                    # from harness.ports requires `from harness.ports import X`.
                    if alias.name != "harness.ports":
                        print(
                            f"layer_boundary_violation: {rel}:{node.lineno} {alias.name} (whole module) not in harness/ports allowlist"
                        )
                hits += 1
    elif isinstance(node, ast.ImportFrom):
        if not _is_harness_module(node.module):
            return 0
        if node.module != "harness.ports":
            # Report each imported symbol separately so the violation names
            # the exact symbol (per the I/O Matrix contract) — even though
            # the entire module is off-limits.
            for alias in node.names:
                name = alias.asname or alias.name
                print(
                    f"layer_boundary_violation: {rel}:{node.lineno} {node.module}.{name} not in harness/ports allowlist"
                )
                hits += 1
            return hits
        for alias in node.names:
            name = alias.asname or alias.name
            if name == "*":
                # `from harness.ports import *` — trust the module's __all__.
                continue
            if name not in allowed:
                print(
                    f"layer_boundary_violation: {rel}:{node.lineno} {name} not in harness/ports allowlist"
                )
                hits += 1
    return hits


def _scan_root(root: Path, allowed: set[str]) -> int:
    """Walk every *.py under root and return violation count. The root must
    exist; missing layer roots are flagged separately by the caller.
    """
    hits = 0
    for py_file in iter_python_files(root):
        tree_or_error = parse_python_file(py_file)
        if not isinstance(tree_or_error, ast.Module):
            _, err = tree_or_error
            print(f"layer_boundary_violation: {py_file.as_posix()}:{err}")
            hits += 1
            continue
        for node in ast.walk(tree_or_error):
            hits += _check_import(node, py_file, allowed)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ports-path",
        default=None,
        help="Path to harness/ports/__init__.py (the allowlist source). Default: <script-parent>/harness/ports/__init__.py",
    )
    parser.add_argument(
        "--layer-dir",
        default=None,
        help="Parent of the four skills/agents/herdr/dashboard layer roots. Default: <script-parent>.",
    )
    parser.add_argument(
        "--var-dir",
        default=None,
        help="Parent of the four var/<layer>/ skeleton subdirs. Default: <layer-dir>/var.",
    )
    parser.add_argument(
        "--layer-root",
        action="append",
        default=None,
        help="Layer root name to scan (repeatable; default: skills, agents, herdr, dashboard).",
    )
    args = parser.parse_args()

    script_parent = Path(__file__).resolve().parent.parent
    ports_path = Path(args.ports_path).resolve() if args.ports_path else script_parent / "harness" / "ports" / "__init__.py"
    layer_dir = Path(args.layer_dir).resolve() if args.layer_dir else script_parent
    var_dir = Path(args.var_dir).resolve() if args.var_dir else layer_dir / DEFAULT_VAR_DIR_NAME
    layer_roots = args.layer_root if args.layer_root else list(DEFAULT_LAYER_ROOTS)

    allowed, err = _load_allowlist(ports_path)
    if err is not None:
        print(err)
        return 1

    hits = 0
    # Check the four var/<layer>/ subdirs exist (deploy-required markers).
    for layer in layer_roots:
        marker = var_dir / layer
        if not marker.exists():
            print(f"missing_layer_root: {marker.as_posix()}")
            hits += 1
    # Scan the four layer roots.
    for layer in layer_roots:
        root = layer_dir / layer
        if not root.exists():
            print(f"missing_layer_root: {root.as_posix()}")
            hits += 1
            continue
        hits += _scan_root(root, allowed)

    if hits == 0:
        return 0
    print(f"\nAD-26 violation: {hits} layer-boundary issue(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
