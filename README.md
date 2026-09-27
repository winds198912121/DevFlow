# DevFlow Harness

Long-lived AI agent platform for software development. The development
workflow (`software-v1`, six steps: research → design → coding → testing →
review → delivery) stays fixed while the agents, LLMs and skills behind
each step can be swapped and benchmarked across projects.

This repository is the harness control plane. BMAD Method skills supply
the per-step "how"; Herdr runs out-of-process as an optional observability
feed.

## Verify (Epic 1 Story 1.1)

```bash
uv sync
uv lock --check                       # bit-identical lockfile across clones
uv run harness --help                 # Typer help listing check-baseline
uv run harness check-baseline         # exit 0 (stub until Story 1.6)
```

## Planning artifacts

- `_bmad-output/specs/spec-devflow/` — the machine contract every downstream skill consumes.
- `_bmad-output/planning-artifacts/prds/` — the PRD that the SPEC distills.
- `_bmad-output/planning-artifacts/architecture/` — the architecture spine (26 ADs).
- `_bmad-output/preview-ticketing/` — the GitHub-published ticketing tree.
- `_bmad-output/contracts/` — JSON Schemas for `test-report.json` and Acknowledgement records.
