#!/usr/bin/env python3
"""Stub for the dashboard-write allowlist CI lint (AD-21).

Story 1.6 ships this stub so `harness check-baseline` has something to invoke
when it runs `check_dashboard_write_lint`. The stub exits 0 and prints a
single line declaring its deferred status; the baseline honestly reports
the dashboard-write lint as not-yet-implemented.

Story 1.7 replaces this body with the real AST-walking lint (mirrors
`tools/check_layer_boundaries.py`).
"""

from __future__ import annotations

print("dashboard_write_lint: deferred (Story 1.7 will replace this stub)")
raise SystemExit(0)
