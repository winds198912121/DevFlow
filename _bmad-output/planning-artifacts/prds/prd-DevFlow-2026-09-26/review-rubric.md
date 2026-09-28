# PRD Quality Review — DevFlow Harness

## Overall verdict

The PRD earns its conclusions: the thesis (fixed workflow + swappable executors + benchmark-driven recommendation) holds cleanly across Vision, Features, Success Metrics, and Non-Goals, and most decisions are surfaced with explicit stances and `[NOTE FOR PM]` callouts. Downstream usability is mostly solid — globally numbered FRs, glossary-first structure, named UJ protagonists — but a broken `FR-39` cross-reference in UJ-2, a `12 NFRs vs 8 NFRs` mismatch between `addendum.md §A7` and PRD §10, and the loose interaction between FR-10's Acknowledgement contract and FR-12's size-tier Gate skipping are real blockers for `bmad-spec` and `bmad-ticketing`.

## Decision-readiness — adequate

Stated decisions are clear: D4 (pin + regression), D5 (signed approval record, tentative), D3 (observe-only Herdr), D6 (v2 dynamic router — out of MVP), `data-v1`/`ml-v1` (vision-only). The retry ladder has explicit rungs. FR-6 names the cost of pin enforcement (`A bumped skill version that fails the regression set produces a skill_regression_failed error record`). §6.2 carries `[NOTE FOR PM]` callouts on MVP boundaries that haven't been decided (which 1–2 Agent adapters ship v1).

But the retry ladder contradicts itself on rung 4 ("improved Skill") — FR-6 forbids auto-upgrade and FR-23 requires manual operator promotion, yet FR-15 reads as if the harness itself can bump the Skill mid-retry. Either rung 4 is operator-initiated (operator edits YAML + manually promotes the bump before the retry) and the ladder as phrased is misleading, or the ladder as written is impossible under v1's pin policy. Also, 4 of 7 Open Questions (OQ-1 router location, OQ-2 `test-report.json` schema, OQ-6 v1 Agent adapters, OQ-7 skill/contract ownership) carry no PRD stance — they defer to architecture/spec without naming what would tip the decision.

### Findings
- **high** Retry-ladder rung 4 in tension with FR-6 / FR-23 (§4.4 FR-15) — "improved Skill" implies harness-side promotion, but FR-6 forbids auto-upgrade and FR-23 requires manual operator promotion. *Fix:* make rung 4 explicitly operator-initiated, or rename it "different Skill (operator-promoted bump before retry)".
- **medium** 4 of 7 Open Questions lack a PRD stance (OQ-1, OQ-2, OQ-6, OQ-7) (§8). *Fix:* either write a tentative stance (e.g. OQ-1 "PRD prefers sidecar; confirm in arch"), or rename them `[DEFERRED]` and surface the criteria that would tip the decision.

## Substance over theater — strong

Personas (Mei, Arjun, Lin) each carry context that drives at least one feature cluster; none are decorative. Vision's thesis ("workflow stays fixed while the agents, LLMs and skills behind each step can be swapped and benchmarked") is product-specific — it cannot swap into a different PRD without changing meaning. NFRs carry product-specific thresholds (≤10× executor first-token latency, ≤1s query latency for 10k records, hash stability across re-renders, 100% locked-artifact durability). No boilerplate "must be scalable / secure / reliable" anywhere. Success Metrics validate the thesis (SM-1 workflow adherence, SM-2 swap success, SM-4 benchmark recommendation, SM-5 bump regression gate) and Counter-metrics (SM-C1 raw success rate, SM-C2 project volume, SM-C3 bump volume) explicitly reject the wrong optimization targets. §12 "Why Now" makes a substantive novelty claim ("fixed workflow + swappable execution + BMAD method + Herdr observation — exists in pieces, not integrated"), not generic innovation theater.

### Findings
- None.

## Strategic coherence — strong

The thesis threads through Vision (§1), Features (FR-1/FR-2 fixed workflow, FR-7 swappable, FR-20/21/22 benchmark-driven), Success Metrics (SM-1, SM-2, SM-4, SM-5), and Non-Goals (§5 "Not a single-agent wrapper", "Not a BMAD replacement"). Counter-metrics named where SMs exist (SM-C1 rejects raw success rate as a value metric; SM-C2 rejects project volume; SM-C3 rejects bump volume). Scope is honestly platform-shape — single-org harness for a 1–5 person team — and the §6.2 deferrals (which 1–2 Agents ship, dynamic router) match the platform bet. MVP scope kind is platform; the scope logic that matches (one canonical pipeline v1, defer other pipelines) is consistent.

### Findings
- None.

## Done-ness clarity — adequate

Most FRs carry `Consequences (testable):` blocks with concrete observable outcomes and error codes (`pipeline_not_found`, `pipeline_immutable`, `unknown_step`, `skill_pin_required`, `artifact_locked`, `error_store_immutable`, `category_not_found`, `skill_regression_failed`, `non_comparable_set`, `non_deterministic_executor`, `human_intervention_required`). The error-code vocabulary is rich enough that downstream can write smoke tests per FR. NFRs have specific numeric thresholds where they have them.

But FR-10's `verdict` vocabulary (`accepted` / `rejected`) is narrower than FR-9's (`accepted` / `accepted-with-open-items` / `rejected`) — the in-between state has no Acknowledgement record path defined. FR-12's `trivial` tier "default Done on a single confirm, no formal Gate" interacts badly with FR-10's blanket Acknowledgement requirement: if there's no Gate, there's no Acknowledgement record, but the addendum §A2 D5 says every Gate needs an Acknowledgement. The PRD does not reconcile this for the size-tier interaction. NFR-Perf-1 ("≤10× the underlying executor's first-token latency") is unmeasurable if the executor doesn't expose first-token latency as a property — and the PRD does not name the fallback.

### Findings
- **high** FR-10 vs FR-12 reconciliation missing (§4.3) — `trivial` / `session` tiers' "skip Gate" semantics leave the Acknowledgement record undefined for those tiers. *Fix:* in FR-10 add a clause "if a Gate is not enforced by size tier, no Acknowledgement record is required for that step"; or have FR-12 explicitly list the implicit `verdict` source (e.g. "auto-`accepted` at step end").
- **medium** Verdict vocabulary gap (§4.3 FR-9 vs FR-10) — `accepted-with-open-items` appears in FR-9 but not FR-10. *Fix:* add `accepted-with-open-items` to FR-10's testable consequences (Acknowledgement with that verdict; artifact transitions to `locked` with an `open_items[]` field attached).
- **medium** "Done" semantics under-specified (§4.3 FR-12) — `trivial`-tier "default Done on a single confirm" doesn't name the operator-visible signal. *Fix:* "trivial-tier Done is the run-status surface showing `Completed` with the single confirmation recorded as `confirm_id`."
- **medium** NFR-Perf-1 measurement ambiguity (§10) — depends on executor exposing `first-token latency`. *Fix:* "if executor does not expose first-token latency, fallback is harness-measured `start_to_first_byte` against a fixed harness-side baseline (e.g. ≤ 30s)".

## Scope honesty — strong

§5 Non-Goals is honest (8 explicit non-goals: not end-user/chat, not single-agent wrapper, not BMAD replacement, not Herdr control plane, not auto-promotion, not fine-tune, not multi-tenant, not `data-v1`/`ml-v1`). §6.2 Out-of-MVP carries `[NOTE FOR PM]` and `[NON-GOAL for MVP]` tags on items that could silently be assumed (Herdr lifecycle, multi-tenant, fine-tuning, other pipelines, auto-promotion, dynamic router). Assumptions Index (§9) lists 5 assumptions with rationale; A3/A4/A5 are new assumptions made by the PRD (not brief carryover) and each names its counter-argument (A3: "store compaction for size — deferred to v2"). Brief deferred findings D1–D6 are tracked in `addendum.md §A2` with status (resolved / tentative / open / deferred to v2). High-severity unresolved items (D2 `test-report.json` schema, D5 Gate acceptance shape) are flagged as gates to `bmad-spec`.

### Findings
- None.

## Downstream usability — adequate

Glossary is comprehensive (§3, ~28 terms) and used verbatim in FRs. FRs are globally numbered (FR-1 … FR-29) and each carries "Realizes UJ-N" cross-references. UJs have named protagonists (Mei, Arjun, Lin) with explicit entry state / path / climax / resolution / edge case. Addendum's A5 (size-tier Gate strictness table) and A6 (step ↔ BMAD skill ownership table) pre-feed architecture/ticketing with concrete content.

But UJ-2's edge case refers to `(FR-39)` for the retry ladder — only FR-1 to FR-29 exist. The intent is clearly FR-15, but a downstream consumer scripting against FR IDs will hit a hard break, and the PRD §0 explicitly promises stable references. The addendum §A7 says "12 NFRs"; PRD §10 carries 8 (NFR-Perf-1, NFR-Perf-2, NFR-Reliab-1, NFR-Reliab-2, NFR-Obs-1, NFR-Obs-2, NFR-Sec-1, NFR-Sec-2) — likely the §11 Cost/Privacy/Safety guardrails should have been numbered NFRs to reach 12.

### Findings
- **critical** Broken cross-reference `(FR-39)` (§2.3 UJ-2 edge case) — only FR-1 … FR-29 exist; intent is FR-15. *Fix:* change to `(FR-15)`; audit all cross-references via the FR table in §4 before next review.
- **high** Addendum/§10 NFR count mismatch (`addendum.md §A7` says "12 NFRs"; `prd.md §10` carries 8) (§10). *Fix:* either recount §10 to 12 by promoting §11's three guardrails into numbered NFRs (NFR-Cost-1, NFR-Privacy-1, NFR-Safety-1), or correct the addendum count to 8.

## Shape fit — strong

Calibration is honest. PRD is for an internal capability spec consumed by `bmad-architecture` → `bmad-spec` → `bmad-preview-ticketing`. The "Scope dial: Heavier" note in §2.3 explicitly opts into UJ density; 3 UJs map to 3 distinct capability clusters (full-pipeline run, mid-run swap, post-hoc audit) — not the "UJ density for a single-operator tool" over-formalization the rubric warns against. Glossary-first structure, globally numbered FRs, and explicit `[NOTE FOR PM]` / `[OPEN]` / `[NON-GOAL for MVP]` markers are appropriate for the chain-top shape. Brownfield nuance is handled by the brief addendum's D1–D6 traceability rather than buried in FRs.

### Findings
- None.

## Mechanical notes

- **Glossary / body terminology drift** (§3 vs body) — Glossary defines "Execution layer" as `Herdr runtime`; body text uses "execution observation layer" for Herdr (e.g., §1 Vision, FR-28 description, §9 A5). Minor; pick one term and use it consistently.
- **`Default Done` not defined** — appears in FR-12 consequences and addendum §A5 table ("default Done" on multiple cells) but is never formally defined. One-line Glossary entry would close this.
- **`Run status` vs `run-state`** — PRD uses both interchangeably (e.g. `run state` in FR-9, `run-status` in FR-24 / FR-26 / FR-27 surface names). Cosmetic.
- **Open Questions vs PRD stance** — 3 of 7 OQs (OQ-3, OQ-4, OQ-5) carry tentative stances; the other 4 (OQ-1, OQ-2, OQ-6, OQ-7) have none. Not broken; worth knowing for downstream triage.
- **Assumptions Index roundtrip** — PRD does not use inline `[ASSUMPTION]` tags in body text (the brief's tags were promoted to facts by user approval per addendum §A1). §9 indexes A3, A4, A5 as new; A1, A2 are brief carryover. No contradiction.
- **Required sections** — all sections the chain-top shape needs are present (Vision, Glossary, Features with globally-numbered FRs, NFRs, Constraints, Non-Goals, MVP Scope, Success Metrics, Open Questions, Assumptions Index). Why Now (§12) is the "Adapt-In" template section; it does work for this PRD (churn framing).