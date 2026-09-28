#!/usr/bin/env python3
"""CI lint: enforce AD-17 — only harness.canonical.py may import hashlib.

AST-walks every *.py under the repo and rejects any `hashlib` import whose
file is not `harness/canonical.py`. Exits 0 on clean, 1 on any hit, with
one line per hit naming the offending file:line and the imported name.

Usage: `uv run python tools/check_no_direct_sha256.py`
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("harness", "agents", "skills", "herdr", "dashboard", "tools", "tests")
ALLOWED = {Path("harness/canonical.py").as_posix()}


def _is_hashlib_import(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == "hashlib":
                return alias.asname or alias.name
    elif isinstance(node, ast.ImportFrom):
        if node.module == "hashlib":
            # `from hashlib import sha256` — name any imported symbol.
            return ", ".join(a.asname or a.name for a in node.names)
    return None


def main() -> int:
    hits = 0
    for scan_dir in SCAN_DIRS:
        scan_path = ROOT / scan_dir
        if not scan_path.exists():
            continue
        for py_file in sorted(scan_path.rglob("*.py")):
            rel = py_file.relative_to(ROOT).as_posix()
            if rel in ALLOWED:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                print(f"direct_hashlib_use: {rel}:SYNTAX_ERROR {e}", file=sys.stderr)
                hits += 1
                continue
            for node in ast.walk(tree):
                imported = _is_hashlib_import(node)
                if imported is not None:
                    print(f"direct_hashlib_use: {rel}:{node.lineno} {imported}")
                    hits += 1
    if hits == 0:
        return 0
    print(f"\nAD-17 violation: {hits} direct hashlib import(s) outside harness/canonical.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
