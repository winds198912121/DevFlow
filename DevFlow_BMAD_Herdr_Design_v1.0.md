# AI Multi-Agent 开发平台 设计书

## BMAD + DevFlow + Herdr + Multi-Agent / Multi-LLM

**Version:** 1.0\
**Status:** Draft\
**System Name:** DevFlow\
**Method Layer:** BMAD Method\
**Runtime / Control Plane:** Herdr

## 1. 设计目的

建立一套可长期迭代的软件开发 AI Agent 平台。

> 固定软件开发 Workflow，通过不同 Project 持续实验 Agent、LLM、Skill
> 的组合，收集执行结果和错误，不断优化每一个开发阶段。

核心原则：

1.  Workflow 固定
2.  Agent 可替换
3.  LLM 可替换
4.  Skill 可替换和持续改进
5.  Artifact 作为 Step 之间的正式接口
6.  所有执行过程必须记录
7.  错误结构化保存
8.  多 Project 持续 Benchmark
9.  最终根据历史数据自动选择 Agent / LLM / Skill

## 2. 总体架构

``` text
BMAD Method Layer
        |
        v
DevFlow Experiment Layer
        |
        v
Herdr Runtime / Control Plane
        |
        +-- Pi
        +-- OMP
        +-- Codex
        +-- Claude Code
        +-- DeepSeek Harness
                |
                v
GPT / Claude / Gemini / MiniMax / DeepSeek / Qwen / Ollama
```

-   **BMAD**：Method / Workflow / Agent Role / Skills / Artifact /
    Context
-   **DevFlow**：Project / Workflow Control / Agent Router / LLM Router
    / Skill Registry / Experiment / Error / Metrics / Benchmark /
    Learning
-   **Herdr**：Runtime / Pane / Session / Logs / Status / Parallel /
    Stop / Retry / Human Control
-   **Agents**：Pi / OMP / Codex / Claude Code / DSH 等 Worker
-   **LLMs**：提供底层智能能力

## 3. 固定开发 Workflow

``` text
Research
   |
   v
Design
   |
   +--------+
   v        v
Coding   Testing
   |        |
   +---+----+
       v
     Review
       |
       v
    Delivery
```

  -------------------------------------------------------------------------------------------
  Step              目的                               输入              输出
  ----------------- ---------------------------------- ----------------- --------------------
  Research          理解需求、Repository、技术和约束   Requirement +     `research.md`
                                                       Repo              

  Design            架构和详细设计                     `research.md`     `design.md`

  Coding            实现功能                           `design.md`       Code +
                                                                         `change-log.md`

  Testing           验证实现结果                       Code + Design     `test-report.json`

  Review            综合检查需求、设计、代码和测试     All Artifacts     `review.md`

  Delivery          整理最终成果                       Approved          Delivery Package
                                                       Artifacts         
  -------------------------------------------------------------------------------------------

## 4. Step 与执行资源分离

  Step       Agent   LLM       Skills
  ---------- ------- --------- --------------------------
  Research   Pi      MiniMax   research / repo-analysis
  Design     OMP     Claude    architecture / ADR
  Coding     Codex   GPT       coding
  Testing    Pi      Gemini    testing / browser
  Review     OMP     Claude    code-review / security

Workflow 固定，但 Agent、LLM、Skill 可以随 Project 改变。

## 5. Artifact Contract

``` text
Requirement
     |
     v
 Research
     |
 research.md
     |
     v
  Design
     |
 design.md
     |
 +---+-----------+
 v               v
Coding        Testing
 |               |
Code       test-report.json
 |               |
 +-------+-------+
         v
       Review
         |
     review.md
         |
         v
      Delivery
```

Artifact 保证 Agent、LLM、Session 可替换，Step 可重跑，历史结果可比较。

## 6. DevFlow 核心模块

``` text
DevFlow
|-- Workflow Controller
|-- Project Manager
|-- Agent Router
|-- LLM Router
|-- Skill Registry
|-- Artifact Manager
|-- Quality Gate
|-- Retry Manager
|-- Error Collector
|-- Experiment DB
|-- Metrics Engine
|-- Benchmark Engine
`-- Report Generator
```

DevFlow 负责决定当前 Step 使用哪个 Agent、LLM、Skill，并记录结果。

## 7. Agent / LLM Router

第一阶段使用静态配置：

``` yaml
research:
  agent: pi
  model: minimax
design:
  agent: omp
  model: claude
coding:
  agent: codex
  model: gpt
testing:
  agent: pi
  model: gemini
review:
  agent: omp
  model: claude
```

后期根据 Project Type、Step、历史成功率、成本、速度、质量和 Tool
Compatibility 动态选择。

目标：

``` text
P(Success | Step, ProjectType, Agent, LLM, SkillSet)
```

## 8. Skill Registry

``` text
skills/
|-- research/
|   |-- requirement-analysis/
|   |-- repo-analysis/
|   `-- dependency-analysis/
|-- design/
|   |-- architecture/
|   |-- adr/
|   `-- api-design/
|-- coding/
|   |-- frontend/
|   |-- backend/
|   |-- python/
|   |-- sap-cap/
|   `-- sap-fiori/
|-- testing/
|   |-- unit-test/
|   |-- integration-test/
|   |-- browser-test/
|   `-- regression-test/
`-- review/
    |-- code-review/
    |-- security-review/
    `-- requirement-traceability/
```

Skill 来源：BMAD Skills + Custom Skills + Project Learning。

## 9. Project Experiment

每个 Project 都是一次实验。Workflow 不改变，实验变量改变。

-   Project 1：Python CLI Tool
-   Project 2：ADT Web Application
-   Project 3：SAP BTP CAP Application
-   Project N：持续扩展

记录 Agent、LLM、Skill、Result、Time、Cost、Retry、Errors、Quality。

## 10. Error Collection

``` yaml
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

错误分类包括 Requirement / Research / Design / Coding / Testing / Review
/ Agent / LLM / Skill / Tool / Environment / Integration Error。

## 11. Retry Strategy

``` text
Same Agent + Same LLM + Same Skill
              |
            FAIL
              v
Same Agent + Different LLM
              |
            FAIL
              v
Different Agent + Better LLM
              |
            FAIL
              v
Different Agent + Different LLM + Improved Skill
              |
            FAIL
              v
       Human Intervention
```

## 12. Quality Gate

Research Gate：Requirement、Repository、Dependency、Unknown、Risk
已确认。

Design Gate：Architecture、Component、Interface、Data Flow、Risk
已定义。

Coding Gate：Build Success、Feature Implemented、No Critical
Error、Change Log Generated。

Testing Gate：Test Cases、Execution、Failed Cases、Test Report 完成。

Review Gate：Requirement Traceability、Architecture Review、Code
Review、Security Review、Test Review 完成。

## 13. Herdr Integration

Herdr 不作为 Workflow Engine，而作为 Agent Runtime / Control Plane。

``` text
DevFlow
   |
   v
Herdr
   |-- Create Agent
   |-- Create Pane
   |-- Start Session
   |-- Monitor
   |-- Capture Logs
   `-- Return Result
          |
          v
       DevFlow
          |
          v
     Quality Gate
```

## 14. Agent Adapter

``` text
AgentAdapter
|-- PiAdapter
|-- OMPAdapter
|-- CodexAdapter
|-- ClaudeCodeAdapter
|-- DSHAdapter
`-- GenericCLIAdapter
```

统一接口：`start()` / `send()` / `status()` / `output()` / `stop()` /
`retry()`。

## 15. 数据与 Storage

第一阶段使用：

-   SQLite：projects / runs / step_runs / agents / models / skills /
    errors / metrics / experiments
-   Markdown：requirement.md / research.md / design.md / change-log.md /
    review.md
-   JSON：test-report.json / run.json / metrics.json / errors.json

``` text
devflow/
|-- workflow/
|-- skills/
|-- projects/
|   |-- project-001/
|   |   |-- requirement.md
|   |   |-- project.yaml
|   |   |-- artifacts/
|   |   |-- runs/
|   |   `-- errors/
|   `-- project-002/
|-- database/
|   `-- devflow.db
`-- reports/
```

## 16. Continuous Learning

``` text
Project
   |
   v
BMAD Workflow
   |
   v
Agent + LLM + Skill
   |
   v
Result
   |
   +--> Error
   +--> Cost
   +--> Quality
          |
          v
    Experiment DB
          |
          v
    Pattern Analysis
          |
    +-----+------+
    v     v      v
  Skill  Agent  LLM
 Improve Change Change
    +-----+------+
          |
          v
     Next Project
```

## 17. 最终职责边界

> **BMAD 管"怎么开发"；DevFlow 管"这次让谁来开发、记录结果并学习"；Herdr
> 管"Agent 如何运行"；Pi / OMP / Codex 等 Agent 真正执行；LLM
> 提供底层智能。**

## 18. MVP

-   [ ] BMAD Workflow 接入
-   [ ] 固定 Research → Design → Coding/Testing → Review → Delivery
-   [ ] Project 创建
-   [ ] Agent / LLM / Skill 配置
-   [ ] Herdr Agent 启动
-   [ ] Artifact 保存
-   [ ] Quality Gate
-   [ ] Error Logging
-   [ ] Retry
-   [ ] SQLite Execution History
-   [ ] Project Report
-   [ ] Project Comparison

第一阶段目标：

``` text
BMAD Workflow
      |
      v
DevFlow
      |
      v
Herdr
      |
      v
Pi / OMP / Codex
```

## 19. Roadmap

1.  **Phase 1 --- BMAD + Herdr**：跑通完整 Workflow。
2.  **Phase 2 --- Experiment DB**：保存 Run / Agent / LLM / Skill /
    Error / Cost / Time / Retry。
3.  **Phase 3 --- Skill Evolution**：Error → Root Cause → Skill Change →
    Next Project Validation。
4.  **Phase 4 --- Benchmark**：分析
    `Agent × LLM × Skill × Step × Project Type`。
5.  **Phase 5 --- Dynamic Router**：自动选择 Best Agent + Best LLM +
    Best Skill Set。
6.  **Phase 6 --- Visual Dashboard**：可视化
    Workflow、状态、成本、错误和 Artifacts。

## 20. 最终目标

> **Self-Improving Multi-Agent Software Engineering System**

最终形成三个核心资产：

1.  **Workflow Asset** --- 稳定的软件工程开发流程
2.  **Skill Asset** --- 从真实项目错误中持续提炼的可复用能力
3.  **Experiment Data Asset** --- Agent × LLM × Skill
    在不同任务上的真实执行数据
