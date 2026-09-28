"""Concrete ExecutorAdapter implementations.

Future adapters (Pi, OMP, Codex, Claude Code, DSH) live here as siblings
of `human.py`. Each adapter registers itself with `harness.executor.ADAPTER_REGISTRY`
on import via the same `_register_<name>()` pattern used for `human` in
`harness/executor.py`.
"""
