#!/usr/bin/env python3
"""CI lint: enforce AD-21 — the dashboard write allowlist.

Scans every *.py under `dashboard/` for FastAPI write route decorators
(`@app.post(...)`, `@app.put(...)`, `@app.patch(...)`, `@app.delete(...)`,
and the same on `@router.<method>(...)`). For each route, extracts the
path from the first positional or `path=` keyword argument and asserts
that the (method, path) pair is in the allowlist.

Default allowlist (the seven routes the spine's AD-21 + AD-18 enumerate):
    POST   /acknowledgements
    POST   /swap-executor
    POST   /skill-bump-regression
    POST   /skill-bump-promote
    POST   /cost-overrun-ack
    POST   /regression-set-remove
    POST   /project-edit-lock

Override with `--allowlist METHOD:/path,METHOD:/path,...` (test affordance).

Exits 0 on a clean dashboard, 1 on any violation. Prints one line per
violation: `dashboard_write_violation: <file>:<lineno> <METHOD> <path>`.
The final line of failure output is `AD-21 violation: N dashboard write(s)
outside allowlist` to mirror tools/check_layer_boundaries.py's summary style.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

WRITE_METHODS = ("post", "put", "patch", "delete")
DECORATOR_PREFIXES = ("app", "router")  # both @app.X and @router.X are routed

# AD-21 (six routes) + AD-18 (project_edit_lock).
DEFAULT_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/acknowledgements"),
        ("POST", "/swap-executor"),
        ("POST", "/skill-bump-regression"),
        ("POST", "/skill-bump-promote"),
        ("POST", "/cost-overrun-ack"),
        ("POST", "/regression-set-remove"),
        ("POST", "/project-edit-lock"),
    }
)


def _is_write_decorator(node: ast.AST) -> tuple[str, str] | None:
    """Return (METHOD, attribute) if `node` is `@app.<write_method>(...)` /
    `@router.<write_method>(...)`, else None.

    Returns the attribute name (e.g. "post"); the method is upper-cased by
    the caller after path extraction succeeds.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name):
        return None
    if func.value.id not in DECORATOR_PREFIXES:
        return None
    if func.attr not in WRITE_METHODS:
        return None
    return func.attr.upper(), func.attr


def _extract_path(call: ast.Call, file: Path, lineno: int) -> tuple[str | None, str | None]:
    """Extract the route path from the decorator call. Returns (path, error).

    path is None and error is set on failure (empty path, non-string, etc.).
    path is set and error is None on success.
    """
    # First positional argument
    if call.args:
        first = call.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            return None, "non_string_path"
        if first.value == "":
            return None, "empty_path"
        return first.value, None
    # `path=` keyword argument
    for kw in call.keywords:
        if kw.arg == "path":
            if not isinstance(kw.value, ast.Constant) or not isinstance(kw.value.value, str):
                return None, "non_string_path"
            if kw.value.value == "":
                return None, "empty_path"
            return kw.value.value, None
    # No path argument at all
    return None, "missing_path"


def _scan_file(path: Path, allowlist: frozenset[tuple[str, str]]) -> list[tuple[Path, int, str, str | None, str | None]]:
    """Return a list of (file, lineno, method, path, error) tuples for every
    write route found in the file. error is None when path extracted cleanly;
    error is a string when path extraction failed (empty / non-string / missing).
    """
    findings: list[tuple[Path, int, str, str | None, str | None]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        findings.append((path, 0, "SYNTAX_ERROR", None, str(e)))
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            write_attr = _is_write_decorator(decorator)
            if write_attr is None:
                continue
            method, _ = write_attr
            route_path, error = _extract_path(decorator, path, node.lineno)
            findings.append((path, decorator.lineno, method, route_path, error))
    return findings


def _parse_allowlist(spec: str) -> frozenset[tuple[str, str]]:
    """Parse `--allowlist 'POST:/a,PUT:/b'` into a frozenset."""
    if not spec.strip():
        return frozenset()
    pairs: set[tuple[str, str]] = set()
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            print(f"invalid allowlist entry: {entry!r} (expected METHOD:/path)", file=sys.stderr)
            sys.exit(2)
        method, path = entry.split(":", 1)
        method = method.strip().upper()
        path = path.strip()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            print(f"invalid method in allowlist entry: {entry!r}", file=sys.stderr)
            sys.exit(2)
        pairs.add((method, path))
    return frozenset(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dashboard-root",
        default="dashboard",
        help="Path to the dashboard directory to scan (default: ./dashboard).",
    )
    parser.add_argument(
        "--allowlist",
        default=",".join(f"{m}:{p}" for m, p in DEFAULT_ALLOWLIST),
        help=(
            "Comma-separated METHOD:/path allowlist (default: AD-21 + AD-18 "
            "seven routes). Pass an empty string for the no-routes baseline."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root for resolving --dashboard-root (default: script's parent).",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parent.parent
    dashboard_root = (project_root / args.dashboard_root).resolve()
    allowlist = _parse_allowlist(args.allowlist)

    if not dashboard_root.exists():
        # No dashboard dir at all → vacuously clean.
        return 0

    findings: list[tuple[Path, int, str, str | None, str | None]] = []
    for py_file in sorted(dashboard_root.rglob("*.py")):
        findings.extend(_scan_file(py_file, allowlist))

    violations = 0
    for file, lineno, method, route_path, error in findings:
        if route_path is None:
            # Path extraction failed — flag as violation regardless of allowlist
            print(f"dashboard_write_violation: {file.as_posix()}:{lineno} {method} <{error}>")
            violations += 1
            continue
        key = (method, route_path)
        if key not in allowlist:
            print(
                f"dashboard_write_violation: {file.as_posix()}:{lineno} {method} {route_path} not in allowlist"
            )
            violations += 1

    if violations == 0:
        return 0
    print(f"\nAD-21 violation: {violations} dashboard write(s) outside allowlist", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
