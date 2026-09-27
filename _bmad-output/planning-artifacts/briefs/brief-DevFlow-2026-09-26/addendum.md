# Product Brief Addendum: DevFlow

**Status:** draft (headless)
**Generated:** 2026-09-26
**Purpose:** Depth that does not fit the brief itself but belongs in the next downstream artifact (PRD, architecture, solution design). Mirrors the local design doc and the BMAD comparison proposal that supplied the inputs.

---

## 1. Source Inputs

- `DevFlow_BMAD_Herdr_Design_v1.0.md` — internal design doc, v1.0 Draft, naming the fixed `software-v1` workflow, Herdr runtime, BMAD method layer, and the five goals G1–G5.
- `BMAD 对比提案.md` — Sep 26 2026, internal proposal that compares BMAD Method against the design doc and the "全体图 (full-system diagram)", recommending a three-layer split: Harness (this design) → BMAD Skills (method layer) → Herdr (optional execution).
- `image.png`, `Bmad.png` — diagrams referenced by the proposal.
- `BMad_Method_4_Stage_Skill_Catalog.xlsx` — BMAD skill catalog. Not ingested in this brief; deferred to the architecture step.

## 2. Three-Layer Architecture (canonical)

```
┌──────────────────────────────────────────────────────────┐
│  ① Harness / Control Plane  — DevFlow (this design)     │
│     workflow controller · project manager · agent       │
│     router · LLM router · skill registry · artifact     │
│     manager · quality gate · retry manager · error      │
│     collector · experiment DB · metrics · benchmark ·    │
│     report generator                                    │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  ② Method Layer — BMAD Skills                            │
│     brief · PRD · spec · architecture · build ·         │
│     retrospective · QA · walkthrough · ticketing …      │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  ③ Execution Layer — Herdr (optional observation)       │
│     Pi · OMP · Codex · Claude Code · DeepSeek Harness    │
│     → GPT / Claude / Gemini / MiniMax / DeepSeek / Qwen │
└──────────────────────────────────────────────────────────┘
```

Key rule from the proposal: **Herdr is an observation layer, not the control plane**. The harness owns state and gates.

## 3. Mapping BMAD Skill to Workflow Step

| Workflow step | Primary BMAD skill | Supporting skills                       | Artifact the step produces | Gate acceptance |
|---------------|--------------------|-----------------------------------------|---------------------------|-----------------|
| Research      | `bmad-deep-recon`  | `bmad-product-brief`, `bmad-forge-idea` | `research.md` (cited) + optional `brief.md` | Intention three-piece is clear: what is true when done, what cannot change, what is out of scope |
| Design        | `bmad-spec`        | `bmad-prd`, `bmad-architecture`, `bmad-ux` | `prd.md`, `ARCHITECTURE-SPINE.md`, `SPEC.md` | Requirements covered, acceptance criteria measurable |
| Coding        | `bmad-build` / `bmad-build-auto` | `bmad-preview-ticketing`        | `tickets.toml`, code commits, `change-log.md` | Build + unit tests pass; key story sub-gates acknowledged |
| Testing       | (no BMAD skill)    | project-defined `testing@n`             | `test-report.json` + execution evidence | All acceptance cases executed, E2E evidence attached |
| Review        | `bmad-retrospective` | `bmad-code-review` (built into build) | `review.md` + retro doc | accepted / accepted-with-open-items / rejected verdict |

## 4. Project Size Tiers (from BMAD)

| Tier        | Definition                          | v1 DevFlow behavior |
|-------------|--------------------------------------|---------------------|
| `trivial`   | Edit-and-verify                      | Default Done on a single confirm; no formal Gate |
| `session`   | One-session implementation         | All six steps, light Gate on Design only |
| `epic`      | Multi-story, ~5–20 sessions         | All steps; sub-Gates on key stories; human-first for the first N stories |
| `project`   | 20+ implementation sessions         | All steps; full Gate at every step; benchmark fed back into Skill Registry |

## 5. Error Schema (per design doc §10)

```yaml
project: project-001
step: coding
agent: codex
model: gpt

error:
  category: requirement_misunderstanding
  description: authentication requirement ignored

root_cause:
  - design document unclear
  - coding agent failed to validate acceptance criteria

correction:
  - improve design skill
  - add acceptance-criteria-check skill

retry:
  agent: omp
  model: claude

result:
  status: passed
```

Error categories (closed list): requirement, research, design, coding, testing, review, agent, llm, skill, tool, environment, integration.

## 6. Retry Strategy (per design doc §11)

```
Same Agent + Same LLM + Same Skill          → FAIL
  └─ Same Agent + Different LLM            → FAIL
      └─ Different Agent + Better LLM      → FAIL
          └─ Different Agent + Different LLM + Improved Skill → FAIL
              └─ Human Intervention
```

Harness must persist the failure at every step, not collapse them — otherwise the error store lies.

## 7. Rejected / Deferred (from the proposal)

The following ideas were raised by the design doc and the comparison proposal and **explicitly not adopted** in this brief:

1. Herdr as the control plane → **rejected**: Herdr stays as optional observation; control stays in the harness.
2. Coding and Testing as "parallel execution" → **clarified**: test design parallel, test execution after coding.
3. Step choice by raw success rate → **clarified**: choice is from the regression suite, not raw rate.
4. Auto-promotion of BMAD Skill upgrades → **out of v1**: manual promotion with required regression pass.
5. Native UI / chat surface for end users → **out of v1**: operator dashboards only.

## 8. Deferral Records (BMAD `deferred-findings` style)

These are open items captured here, not in the brief, so the brief stays tight:

| ID | Title | Source | Severity | Location |
|----|-------|--------|----------|----------|
| D1 | v1 router — static YAML in repo or sidecar service? | design doc §7 | medium | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |
| D2 | `test-report.json` v1 schema not defined | design doc §5 + proposal §4 | high | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |
| D3 | Herdr v1 scope — observe-only or full lifecycle? | design doc §2 + proposal §3 | medium | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |
| D4 | BMAD Skill version pin policy | proposal §5 | medium | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |
| D5 | Human Gate acceptance shape | proposal §3.1 | high | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |
| D6 | Dynamic Agent/LLM router (v2) | design doc §7 | low | `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/` |

## 9. Next-Downstream Recommendations

This brief is ready to feed the next BMAD step. Recommended order:

1. **PRD** — `bmad-prd` from this brief (in a fresh context). Pulls goals G1–G5 into FR/NFR form.
2. **Architecture spine** — `bmad-architecture`. Captures the three-layer split, the artifact contract schema, and the router shape.
3. **Spec** — `bmad-spec`. Forces the 5 goals into testable acceptance.
4. **Ticket pre-split** — `bmad-preview-ticketing` once the SPEC is approved.
5. **Build** — `bmad-build` for the first M=2 stories, then `bmad-build-auto` for the rest.

## 10. Files Produced This Run

- `brief.md` — 1-page product brief (executive shape).
- `addendum.md` — this file.
- `.memlog.md` — append-only run memory, seeded with this run's decisions.