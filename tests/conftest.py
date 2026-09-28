"""Shared fixtures for the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from harness...` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
