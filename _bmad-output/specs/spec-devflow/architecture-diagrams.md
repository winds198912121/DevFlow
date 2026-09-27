# Architecture Diagrams

The spine is the source of truth for all architecture-level diagrams. This companion renders only the subset that downstream spec consumers (epics, stories, builders) need to understand the spec, and points at the spine for the rest.

## 1. Three-layer topology (simplified)

```mermaid
flowchart LR
    subgraph H[Harness control plane]
        WC[Workflow Controller]
        PM[Project Manager]
        RG[Router - in-process]
        QG[Quality Gate Engine]
        ES[(Error Store)]
        RS[(Regression Set)]
        CL[(Cost Ledger)]
        RE[(Run Event Log)]
        AS[(Artifact Store)]
        AC[(Acknowledgement Store)]
        SBR[(Skill Bump Registry)]
        BENCH[Benchmark Engine]
        CG[Cost Guard]
    end

    subgraph M[Method layer - BMAD Skills]
        DR[bmad-deep-recon]
        SP[bmad-spec]
        PR[bmad-prd]
        AR[bmad-architecture]
        BU[bmad-build]
        RE_SK[bmad-retrospective]
        CR[bmad-code-review]
        PT[bmad-preview-ticketing]
    end

    subgraph E[Execution layer]
        AD1[PiAdapter]
        AD2[OMPAdapter]
        AD3[CodexAdapter]
        AD4[ClaudeCodeAdapter]
        AD5[DSHAdapter]
        HMD[HumanMode]
    end

    WC --> PM --> RG
    RG -->|ExecutorAdapter| AD1 & AD2 & AD3 & AD4 & AD5 & HMD
    WC --> QG
    QG --> AC
    QG --> AS
    ES --> RE
    RS --> BENCH
    CL --> CG
    RE --> BENCH
    RE --> CG
    PM -->|reads pinned Skill manifest| M
    WC -->|invokes via ExecutorAdapter| E
```

## 2. Step lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: executor starts
    running --> pending_agent: rung N+1 retry
    running --> paused: cost overrun
    running --> pending_human: rung 4 fails
    pending_human --> pending: operator acknowledges cost_overrun_ack
    paused --> running: cost_overrun_ack
    running --> pending_gate: executor ends (success or fail)
    pending_gate --> locked: gate_mode=enforced + acknowledgement (accepted|with-open-items)
    pending_gate --> locked: gate_mode=skipped (trivial|session)
    pending_gate --> failed: gate_mode=enforced + acknowledgement (rejected)
    pending_gate --> failed: no acknowledgement + tier does not allow skipped
    locked --> [*]
    failed --> pending: retry ladder rung restarts
```

## 3. Acknowledgement path

```mermaid
flowchart LR
    OP[Operator or check] -->|submit_acknowledgement| DH[Dashboard allowlist - AD-21]
    DH -->|AD-5 record shape| WR[Write acknowledgements/project_id/run_id/step/ack_id.json]
    WR -->|sign with canonical_bytes + Ed25519| SIG[signed record]
    SIG --> QG[Quality Gate Engine]
    QG -->|validates path triple| OK{Path matches body?}
    OK -->|yes| ADV[Advance to next step]
    OK -->|no| REJ[acknowledgement_path_mismatch]
    QG -->|verifies Ed25519| VK{Valid signature?}
    VK -->|yes| ADV
    VK -->|no| UNSIG[acknowledgement_unsigned]
```

## 4. Benchmark / regression-set flow

```mermaid
sequenceDiagram
    participant OP as Operator
    participant BENCH as Benchmark Engine
    participant RS as Regression Set
    participant SBR as Skill Bump Registry
    OP->>BENCH: bench <step>
    BENCH->>RS: query (step, project_size_tier, artifact_contract_version)
    RS-->>BENCH: comparable runs (or insufficient)
    alt K comparable runs available
        BENCH->>BENCH: rank by recorded metric
        BENCH-->>OP: recommendation tuple + contributing runs + metric
    else below K=3
        BENCH-->>OP: regression_set_insufficient
    end
    OP->>SBR: register bump <skill>@<new_version>
    SBR->>BENCH: trigger_skill_bump_regression
    BENCH->>RS: run regression set with new pin
    RS-->>BENCH: per-step pass/fail
    BENCH-->>SBR: regression_run_id (result=pass|fail)
    OP->>SBR: promote_skill_bump (requires regression_run_id)
    SBR-->>OP: skill promoted | skill_regression_failed | skill_regression_missing
```

## Source-of-truth pointer

The full architecture spine (26 ADs, full data shapes, dependency direction, layer-boundary enforcement, technology stack, deferred items) lives at `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` and is the adopted companion of this spec. This file is a rendered subset; do not edit the diagrams here and assume the spine reflects the change.
