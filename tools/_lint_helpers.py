"""Shared AST-walking helpers for the tools/*.py lints.

Consolidates the `rglob("*.py") + try/except ast.parse` pattern shared by
`tools/check_layer_boundaries.py` and `tools/check_dashboard_writes.py`.

Internal to the `tools/` package — leading underscore signals "not part of
the public CLI surface". The two lints import this module directly via
`from tools._lint_helpers import iter_python_files, parse_python_file`.

These helpers are intentionally minimal: each is a 5-line function that
does one thing. No third-party dependencies; the standard library `ast`
module is sufficient.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every `*.py` under `root` (recursively), in sorted order.

    Sorted order is intentional: lints emit one violation per file and the
    `for py_file in sorted(...)` pattern from the pre-refactor code
    preserves determinism across runs.
    """
    yield from sorted(root.rglob("*.py"))


def parse_python_file(path: Path) -> ast.Module | tuple[None, str]:
    """Parse `path` as Python source. Return the AST on success; on SyntaxError
    return `(None, error_message)` so the caller can decide how to surface
    the failure (the layer-boundary lint logs a violation; the dashboard
    lint logs a violation).

    The success-or-tuple convention matches `pathlib.Path.read_text` more
    closely than a tagged-union return: callers test `if isinstance(...)`
    to branch, not `if result[1] is None`.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return None, f"SYNTAX_ERROR {e}"
    except OSError as e:
        # File exists (rglob returned it) but cannot be read — treat as a
        # parse failure rather than letting the exception propagate past
        # the lint loop.
        return None, f"READ_ERROR {e}"
