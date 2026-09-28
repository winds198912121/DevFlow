#!/usr/bin/env python3
"""CI lint: enforce AD-24 (d) — one terminal-status resolver, no inline computation.

AD-24 (b) says every dashboard view must obtain a step's terminal status from
the single resolver; (d) requires a CI hook that fails "any dashboard view that
imports a different terminal-status resolver or computes status from raw
fields". This is that hook.

What it checks, per view module under `dashboard/`
-------------------------------------------------
1. **No second resolver.** An import whose module specifier names a
   status-resolving concern (`step_status`, `gate_engine`, `terminal_status`,
   `resolve_status`, ...) is a violation. The dashboard SPA must reach the
   resolver through the HTTP API, not by importing an implementation.

2. **No computation from raw fields.** The fields the resolver itself consumes
   — `verdict`, `outcome`, `confirm_id`, `acknowledgement_id` — must not appear
   in a view. A view that reads them is one `if` away from a second, divergent
   status rule. This is the checkable form of "computes status from raw
   fields": it draws the line at the resolver's *inputs*, and leaves its
   *outputs* (`terminal`, `gate_mode`) free to be rendered.

The API client module (`dashboard/src/api.ts` by default) is exempt: it declares
the payload types, and therefore names those fields. It is the transport
boundary, not a view. Everything else under `dashboard/` is scanned — including
any future `.js`, so a hand-written view cannot dodge the rule by not being
TypeScript.

Comments and string literals are stripped before scanning, so prose that
explains the rule (as the views do) is not itself a violation.

Args:
  --dashboard-root  Directory to scan (default: ./dashboard).
  --project-root    Base for resolving --dashboard-root.
  --exempt          Module paths to exempt, relative to dashboard root
                    (repeatable; default: src/api.ts).

Exits 0 on a clean dashboard, 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: Module specifiers that name a status-resolving concern. Importing any of
#: these from a view is a second resolver (AD-24 (d), first clause).
_FORBIDDEN_IMPORT = re.compile(
    r"(step[_-]?status|gate[_-]?engine|terminal[_-]?status|resolve[_-]?status|status[_-]?resolv)",
    re.IGNORECASE,
)

#: The resolver's *inputs* per AD-24 (c). A view must consume the resolver's
#: outputs instead, so any of these in a view is inline computation.
_RAW_STATUS_INPUTS = ("verdict", "outcome", "confirm_id", "acknowledgement_id")

_IMPORT_RE = re.compile(
    r"""^\s*(?:import|export)\b[^;]*?\bfrom\s*['"](?P<module>[^'"]+)['"]""",
    re.MULTILINE,
)
#: Comments only — string literals are deliberately left in place so a view
#: cannot name a raw status field inside a template either. Parsing strings
#: would also mean deciding how to treat `//` inside a URL, and getting that
#: wrong silently hides code from the scan.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\b")

DEFAULT_EXEMPT = ("src/api.ts",)

#: Test modules are not views: they build literal payloads — including the
#: fields the resolver consumes — to pin a render. Scanning them would flag
#: fixture data, which is the opposite of a status computation.
_TEST_MODULE_RE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")


def _is_test_module(name: str) -> bool:
    return bool(_TEST_MODULE_RE.search(name))


def _strip_comments(source: str) -> str:
    """Remove comments, preserving line structure.

    Newlines inside a removed span are kept so reported line numbers stay
    accurate. Without this, a view's own docstring explaining the rule would
    trip the very check it documents.
    """

    def blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub(blank, source))


def _scan_file(path: Path, root: Path, exempt: frozenset[str]) -> list[str]:
    rel = path.relative_to(root).as_posix()
    if rel in exempt or _is_test_module(path.name):
        return []
    source = path.read_text(encoding="utf-8")
    code = _strip_comments(source)
    findings: list[str] = []

    for match in _IMPORT_RE.finditer(code):
        module = match.group("module")
        if _FORBIDDEN_IMPORT.search(module):
            line = code[: match.start()].count("\n") + 1
            findings.append(
                f"terminal_status_violation: {rel}:{line} imports "
                f"{module!r} (a second status resolver; AD-24 (d))"
            )

    for lineno, line_text in enumerate(code.splitlines(), start=1):
        for token in _IDENTIFIER_RE.findall(line_text):
            if token in _RAW_STATUS_INPUTS:
                findings.append(
                    f"terminal_status_violation: {rel}:{lineno} reads raw status "
                    f"input {token!r} (compute via the resolver; AD-24 (b)/(d))"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dashboard-root",
        default="dashboard",
        help="Path to the dashboard directory to scan (default: ./dashboard).",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root for resolving --dashboard-root (default: script's parent).",
    )
    parser.add_argument(
        "--exempt",
        action="append",
        default=None,
        help=(
            "Dashboard-relative module path to exempt (repeatable). "
            f"Default: {','.join(DEFAULT_EXEMPT)}"
        ),
    )
    args = parser.parse_args()

    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path(__file__).resolve().parent.parent
    )
    dashboard_root = (project_root / args.dashboard_root).resolve()
    exempt = frozenset(args.exempt if args.exempt is not None else DEFAULT_EXEMPT)

    if not dashboard_root.exists():
        # No dashboard dir at all -> vacuously clean (mirrors the sibling lints).
        return 0

    findings: list[str] = []
    for pattern in ("*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs"):
        for path in sorted(dashboard_root.rglob(pattern)):
            if "node_modules" in path.parts or "dist" in path.parts:
                continue
            findings.extend(_scan_file(path, dashboard_root, exempt))

    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\nAD-24 violation: {len(findings)} terminal-status issue(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
