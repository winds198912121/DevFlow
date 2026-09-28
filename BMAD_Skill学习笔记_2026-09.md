# BMAD Skill 学习笔记

> 依据：`BMAD_项目实战培训手册_Skill代码就地版_2026-09.docx` 与 https://github.com/bmad-code-org/BMAD-METHOD
> 生成时间：2026-09-27
> 用途：固化"Skill 学习方法 + 速查表 + 接缝图"，方便日后查阅与培训复用。

---

## 0. 核心判断（写在最前面）

BMAD 不是一个必须从头跑到尾的流水线，而是一条**按工作复杂度选择上下文深度**的交付循环。GitHub README 与手册 §1 都强调同一句话：

> **Same loop, different depth.** Bigger work enters earlier and goes round more often; it does not become a different way of delivering.

学习任何 Skill 之前，先判断规模再决定路径：

| 规模 | 推荐路径 | 例子 |
|---|---|---|
| **S · 单 Session** | `bmad-build` → 可选 `bmad-code-review` | 改一个 API、修一个 bug、加一个字段 |
| **M · 多个 Story** | `bmad-spec` → epics/stories → `bmad-build × N` → `bmad-retrospective` | 加一个 AI 匹配评分引擎 |
| **L · 完整产品** | Analysis → PRD/UX → Architecture → Epics/Stories → Sprint → Build/Review/QA → Retro | 完整 SAP 顾问智能匹配平台 |

---

## 1. Skill 学习方法（5 步法）

### Step 1 · 看四角形：用途 / 输入 / 产出 / Gate

每个 Skill 在手册 §4–§7 都按这四字段讲。先记**契约**，再去看 SKILL.md：

- **用途**：它在哪个 Stage，回答什么问题
- **输入**：吃什么 artifact / 上下文
- **产出**：吐什么文件 / 决定
- **Gate**：谁人工把关、什么状态才能进入下一步

### Step 2 · 在 GitHub 仓库里读原始 SKILL.md

仓库路径统一是 `src/<module>/<skill>/SKILL.md`，手册 §14 给出了精确路径，例如：

- `src/core-skills/bmad-help/SKILL.md`
- `src/core-skills/bmad-brainstorming/SKILL.md`
- `src/bmm-skills/plan/bmad-prd/SKILL.md`
- `src/bmm-skills/plan/bmad-architecture/SKILL.md`
- `src/bmm-skills/ship/bmad-build/SKILL.md`

**原则：手册只讲"调用方法"，实现源码以安装版本为准。** BMAD 在快速演进（CHANGELOG、releases），复制源码进文档立刻过时。

### Step 3 · 在本地项目安装一次，验证路径

官方安装命令（README）：

```bash
# Skills CLI 路线
npx skills add bmad-code-org/BMAD-METHOD

# 或显式指定 skill
npx skills add bmad-code-org/BMAD-METHOD \
  --skill bmad \
  --skill bmod-core-tools \
  --skill bmod-method \
  --skill bmad-build

# 更新
npx skills update
```

安装后项目内会出现 `.claude/skills/<name>/SKILL.md`（Claude）或 `.agents/skills/...`（Cursor/Windsurf）。**打开一个真实文件，比读十遍描述更有效。**

### Step 4 · 跟一遍手册的 SAP 案例串讲

手册 §2 给的贯穿案例：**SAP 顾问智能匹配与提案系统**。完整 14 步 Skill 流转：

```
bmad-brainstorming → bmad-deep-recon → bmad-brief → bmad-prd → bmad-ux
→ bmad-architecture → bmad-project-context → bmad-create-epics-and-stories
→ bmad-sprint-planning → (bmad-build + bmad-code-review) × N
→ bmad-qa-generate-e2e-tests → bmad-retrospective
```

**原则：用同一份案例跟踪所有 Skill**，能看出相邻 Skill 之间输入输出的接缝。

### Step 5 · 把 Skill 映射到你的执行环境

手册 §10 推荐：**Herdr / OMP 当 Orchestrator，BMAD Skill 当 Node 内部执行器。**

| BMAD 层 | Orchestrator 节点 | 推荐执行者 |
|---|---|---|
| Analysis | Research / Brief Node | scout 子 agent 或 analyst persona |
| Planning | PRD / UX / Spec Node | pm / ux persona |
| Solutioning | Architecture / Ticketing Node | architect persona + planner |
| Implementation | Build worker × N | dev subagent（task agent） |
| Validation | Code Review / QA Node | reviewer + qa-test 子 agent |
| Closure | Retrospective Node | reviewer with pm/architect context |

**关键原则：不要让一个巨型 Agent 从 Idea 一路做到 Merge。** Skill = 节点内部 SOP；Orchestrator = 调度谁、何时跑、传什么。

---

## 2. 四阶段底盘（Skill 地图）

| Stage | 关键问题 | 主流 Skill | 我的产出 |
|---|---|---|---|
| **Analysis 分析** | 为什么做？值得做吗？ | `bmad-help` → `bmad-brainstorming` → `bmad-deep-recon` → `bmad-brief` → `bmad-forge-idea` | brief / research |
| **Planning 规划** | 做什么？边界？成功标准？ | `bmad-prd` → `bmad-ux` → `bmad-spec` → `bmad-review` | PRD / UX / SPEC |
| **Solutioning 方案设计** | 怎么做？跨模块怎么一致？ | `bmad-architecture` → `bmad-project-context` → `bmad-create-epics-and-stories` → `bmad-preview-ticketing` → `bmad-sprint-planning` | architecture / epics / sprint-status |
| **Implementation 实施** | 写出来、验证、复盘 | `bmad-build` → `bmad-code-review` → `bmad-qa-generate-e2e-tests` → `bmad-investigate` → `bmad-correct-course` → `bmad-retrospective` → `bmad-walkthrough` | code / tests / retro |
| **Cross-stage 横切** | 全阶段支持 | `bmad-help` · `bmad-review` · `bmad-advanced-elicitation` · `bmad-party-mode` · `bmad-customize` · `bmad-agent-*` | guidance / override |

---

## 3. Skill 速查表（精简版）

### 安装与状态

```bash
npx skills add bmad-code-org/BMAD-METHOD     # 安装
npx skills update                              # 更新
# 进入 Coding Agent 后：
bmad setup                                     # 生成项目结构
bmad status                                    # 查看版本与可用 Skill
bmad-help 我现在该跑哪个？                     # 路由建议
```

### Analysis 阶段

| Skill | 一句话 | 调用示例 |
|---|---|---|
| `bmad-help` | 看当前进度并推荐下一步 | `bmad-help 我有 PRD 但缺 architecture` |
| `bmad-brainstorming` | 结构化发散 | `bmad-brainstorming 主题：...` |
| `bmad-deep-recon` | 围绕决策做证据级研究 | `bmad-deep-recon 问题：...` |
| `bmad-brief` | 收敛成 Product Brief | `bmad-brief Create / Update / Validate` |
| `bmad-forge-idea` | 苏格拉底式压力测试想法 | `bmad-forge-idea idea=...` |

### Planning 阶段

| Skill | 一句话 | 调用示例 |
|---|---|---|
| `bmad-prd` | WHAT/WHY 完整 PRD | `bmad-prd Create` |
| `bmad-ux` | 设计 + 行为两份文档 | `bmad-ux 基于 PRD 设计 recruiter 流程` |
| `bmad-spec` | 中型功能可执行规格 | `bmad-spec 为评分引擎生成 SPEC` |
| `bmad-review` | 多 lens 审查文档/代码 | `bmad-review 对象=当前 PRD lens=adversarial` |

### Solutioning 阶段

| Skill | 一句话 | 调用示例 |
|---|---|---|
| `bmad-architecture` | 跨 Epic 不可逆决策 | `bmad-architecture 输入=PRD+codebase` |
| `bmad-project-context` | 沉淀项目级 Agent 规则 | `bmad-project-context ingest` |
| `bmad-create-epics-and-stories` | 拆成可执行 Story | `bmad-create-epics-and-stories` |
| `bmad-preview-ticketing` | ticket tree 编排 | `bmad-preview-ticketing slice this initiative` |
| `bmad-sprint-planning` | readiness gate | `bmad-sprint-planning` |

### Implementation 阶段

| Skill | 一句话 | 调用示例 |
|---|---|---|
| `bmad-build` | 交互式实施入口 | `bmad-build 实现 Story 1.2` |
| `bmad-build-auto` | 无人值守推进 ticket | `bmad-build-auto`（供 Orchestrator 调度） |
| `bmad-code-review` | 独立多视角审查 | `bmad-code-review` |
| `bmad-qa-generate-e2e-tests` | 生成 E2E/API 测试 | `bmad-qa-generate-e2e-tests` |
| `bmad-investigate` | 证据分级调查缺陷 | `bmad-investigate 问题=...` |
| `bmad-correct-course` | 重大变更影响评估 | `bmad-correct-course 新约束=...` |
| `bmad-retrospective` | Epic 级证据复盘 | `bmad-retrospective` |
| `bmad-walkthrough` | 人工走查变更 | `bmad-walkthrough commit=...` |

### Cross-stage

`bmad-help` · `bmad-review` · `bmad-advanced-elicitation` · `bmad-party-mode` · `bmad-customize` · `bmad-agent-{analyst|pm|architect|dev|ux-designer}`

---

## 4. 接缝图：相邻 Skill 之间的 artifact 移交

以 SAP 顾问智能匹配系统为贯穿案例，把 14 个 Skill 之间的接缝画清楚：

```
[brainstorming]
   └─→ 想法 + 假设 + 未验证问题
        ↓
[deep-recon]
   └─→ research.md（事实/推断/未知 三分）
        ↓
[brief]   ←── 人工 Gate：方向值得做
   └─→ product-brief.md + decision log
        ↓
[prd]     ←── 人工 Gate：PRD sign-off
   └─→ PRD.md + addendum + memlog
        ↓
[ux]
   └─→ DESIGN.md + EXPERIENCE.md
        ↓
[architecture]  ←── 人工 Gate：spine review
   └─→ architecture artifact + 派生 spec
        ↓
[project-context]
   └─→ project-context.md（所有 Agent 自动读取）
        ↓
[create-epics-and-stories]
   └─→ epics.md + stories.md（每个 Story 含 AC）
        ↓
[preview-ticketing]
   └─→ tickets.toml + ticket plans
        ↓
[sprint-planning]  ←── 人工 Gate：readiness
   └─→ sprint-status.yaml
        ↓
[build + code-review + qa-generate-e2e-tests]
   └─→ 每个 Story 一次新会话
        ↓
[retrospective]
   └─→ epic-<slug>-retrospective.md + verdict
        ↓
        └─ 有重大变化 → [correct-course] → 回到 PRD/Architecture
```

**每个箭头都是一次 artifact 移交 + 人工 Gate。** 这就是 BMAD 的本质：

- 让思考产物**版本化**
- 让 Agent **不重复造轮子**
- 让每个工作单元**大小合适**

---

## 5. 三条最重要的操作规则（手册 §14.5）

1. **每个 workflow 一个新会话** —— 减少上下文污染 + token 爆炸。
2. **不为完整而完整** —— 工作清晰就直接 `bmad-build`，不要机械走全套。
3. **Artifact 才是跨 Session 记忆** —— PRD / SPEC / Architecture / Story / project-context / sprint-status 比聊天历史重要一万倍。

---

## 6. 查 Skill 源码的正确姿势

| 想了解什么 | 去哪里查 |
|---|---|
| 安装方式、最佳入门 | README.md + docs/index.md |
| Skill 用途与执行步骤 | 安装到本地后读 `.claude/skills/<name>/SKILL.md` |
| 上游最新设计 | `https://github.com/bmad-code-org/BMAD-METHOD/tree/main/src` |
| 版本/兼容 shim | CHANGELOG.md + releases |
| 跨 Skill 工作流 | `docs.bmad-method.org/plan/choose-a-planning-path/` |
| 完整交付循环图 | `docs/images/bmad-delivery-loop.svg` |

**原则**：手册不再静态复制 SKILL.md 全文。**先看本笔记解释，再打开本机 SKILL.md 对照**，这是官方与手册共同认可的方式。

---

## 7. 今天就能动手的最小路径

如果想**今天就走一遍**：

1. **判断规模**：S / M / L？不确定就 `bmad-help`。
2. **S**：直接 `bmad-build 在 __改 __`，跑完可选 `bmad-code-review`。
3. **M**：`bmad-spec` → 拆 Story → 每个 Story 一次新会话 `bmad-build`。
4. **L**：按 §3 表跑完整 14 步；每个 Skill 一个新会话；保留 PRD/SPEC/Architecture 作为长期 artifact。
5. **任何阶段**：`bmad-help` 路由 · `bmad-review` 卡门禁 · `bmad-retrospective` 收尾。

---

## 8. 参考链接（手册 §13 + §14.7）

- https://github.com/bmad-code-org/BMAD-METHOD
- https://docs.bmad-method.org/start/build-your-first-change/
- https://docs.bmad-method.org/zh-cn/tutorials/getting-started/
- https://docs.bmad-method.org/workflow-map-diagram.html
- https://docs.bmad-method.org/zh-cn/reference/commands/
- https://docs.bmad-method.org/ko-kr/reference/skills-and-agents/
- https://docs.bmad-method.org/cs/build/build-a-change/
- https://docs.bmad-method.org/build/review-a-change/
- https://docs.bmad-method.org/build/finish-an-epic/
- https://docs.bmad-method.org/zh-cn/explanation/project-context/
- https://docs.bmad-method.org/ko-kr/plan/break-work-into-stories-and-track-it/
- https://docs.bmad-method.org/plan/plan-inside-an-organization/
- https://github.com/bmad-code-org/BMAD-METHOD/blob/main/CHANGELOG.md
- https://github.com/bmad-code-org/BMAD-METHOD/releases