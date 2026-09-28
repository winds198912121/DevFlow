# Failure Modes

How DevFlow detects, records, escalates, and surfaces failures. Two layers: **error categories** (what failed) and **retry ladder** (how to recover).

## Error categories (closed list)

PRD addendum §5 defines 12 closed categories. Each error record carries exactly one.

| Category | Trigger example | Harness action |
| --- | --- | --- |
| `requirement` | Brief or PRD missing required field | Pause; record; surface in dashboard with `category=requirement` filter |
| `research` | `research.md` failed acceptance check | Record; attempt retry-ladder from rung 1 |
| `design` | `SPEC.md` failed acceptance check | Record; attempt retry-ladder from rung 1 |
| `coding` | Build or unit test failed | Record; attempt retry-ladder from rung 1 |
| `testing` | `test-report.json` schema invalid or `acceptance_coverage` below threshold | Record; gate does NOT lock until fixed |
| `review` | Review verdict is `rejected` | Record; do NOT auto-retry (review verdicts are operator decisions) |
| `agent` | Agent adapter unreachable / crashed | Record; retry-ladder starts at rung 1 (same Agent) |
| `llm` | LLM API returned non-recoverable error (rate limit, content filter) | Record; retry-ladder starts at rung 2 (same Agent, different LLM) |
| `skill` | BMAD Skill pin invalid / Skill missing / Skill regression-failed | Record; surface on Skill Bump Registry page; do NOT auto-retry |
| `tool` | Required tool (filesystem, network, signature key) unavailable | Record; operator must intervene (rung 5) |
| `environment` | Harness internal error (DB locked, var/ disk full) | Record; halt the run; operator must intervene (rung 5) |
| `integration` | Harness ↔ executor adapter contract violation | Record; halt the run; engineer must investigate (rung 5) |

## Retry ladder

PRD FR-15 + spine AD-15-shaped policy. The harness executes rung N+1 only after rung N is logged as `FAIL`.

```
Rung 1: same Agent + same LLM + same Skill   → FAIL
  └─ Rung 2: same Agent + different LLM       → FAIL
      └─ Rung 3: different Agent + better LLM → FAIL
          └─ Rung 4: different Agent + different LLM + promoted Skill → FAIL
              └─ Rung 5: human intervention (operator-initiated, NOT auto)
```

Rules:
- Every rung attempt is recorded in the error record's `retry[]` array; no rung is silently skipped.
- Rung 4 may ONLY consume a Skill from the operator-promoted set (`pending_promotion → promoted`); otherwise the harness returns `skill_not_promoted` and pauses the run for operator action (FR-6 + FR-15 + FR-23).
- Rung 5 is operator-initiated; the harness does NOT auto-escalate. A run paused at rung 4 produces `human_intervention_required` and waits.
- Cost ceiling overrun pauses BEFORE the next rung starts (NFR-Cost-2 / `cost_overrun_ack`), not after.

## Cost-overrun pause

Per-tier ceiling (NFR-Cost-2):

| Tier | Default ceiling (logged tokens in + out) |
| --- | --- |
| `trivial` | 5e5 |
| `session` | 5e6 |
| `epic` | 5e7 |
| `project` | 2e8 |
| Skill-bump regression pass | 3× the affected step's normal ceiling |

On overrun:
1. Harness pauses the next step invocation.
2. The step-end run event records `gate_mode: cost_paused`.
3. Operator acknowledges via `cost_overrun_ack` (one of the six allowed dashboard writes per AD-21).
4. The harness resumes on the next invocation; ceiling is not retroactively raised.

## Run state corruption / crash

| Symptom | Harness action |
| --- | --- |
| Harness crash mid-step | NFR-Reliab-2: on restart, completed locked steps are NOT re-run; the in-flight step is reset to `pending` with a new `attempt` counter on the run event |
| Locked artifact hash mismatch on read | NFR-Reliab-1: return `artifact_corrupt`; surface on dashboard with `category=environment` filter; halt the run |
| Acknowledgement signature invalid | AD-5 / NFR-Sec-2: return `acknowledgement_unsigned`; do NOT advance the run; surface in the Gate status |
| Acknowledgement path triple mismatch with body | AD-23: return `acknowledgement_path_mismatch`; same response as unsigned |
| Cost ledger hash mismatch | AD-20: return `cost_ledger_immutable`; engineer must investigate; halt the run |

## What this companion deliberately does NOT specify

- The error record JSON wire format — that's PRD addendum §5.
- The exact pause UX on the dashboard — that's `bmad-ux`.
- The retry-ladder rung 3 ("better LLM") ordering — that's a `bench <step>` question; the ladder consults the regression set, not raw success rate (CAP-5).
- Herdr's role during a failure — Herdr is advisory only (PRD A6); a Herdr outage during a failure does not block the ladder.
