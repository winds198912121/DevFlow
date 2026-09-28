# DevFlow Harness — 开发者参考 (Developer Reference)

> 配套 USER_MANUAL.md:本文件讲的是**这个 session 产出**的 contract 与可移植心智模型,不是用户视角。
> 任何 1-3 个月内回来继续开发的工程师,先读这一份,再读 USER_MANUAL,再读 spine + spec。
>
> 写于 2026-09-28,本 session 全部 26 个 commit 之上。

---

## 0. 这个 session 做了什么

按依赖顺序建了 **Epic 1 (8/8) + Epic 2 前 4 个** 共 12 个 story,后续 Epic 2.5-2.11 + 3 + 4 是当前 main 分支已经合入的代码(不属于本 session)。

| Epic | Story | 产出 |
|---|---|---|
| 1 | 1.1 | uv scaffold + Typer CLI(`harness --help` / `harness check-baseline`) |
| 1 | 1.2 | `harness/canonical.py` —— sole sha256 path(JSON sort + UTF-8 NFC + LF) |
| 1 | 1.3 | `harness/signing.py` + `harness/secrets.py` —— Ed25519 sign/verify on Ed25519 key at `var/secrets/harness.key` (mode 0600) |
| 1 | 1.4 | `harness/ports/__init__.py` 8 个 port Protocol + `tools/check_layer_boundaries.py` (AD-26) |
| 1 | 1.5 | `harness/executor.py` AdapterRegistry + `harness/adapters/human.py` HumanAdapter(boot-time registered) |
| 1 | 1.6 | `harness/checks.py` + `harness/cli.py` 改写 + `harness/__main__.py` —— `harness check-baseline` 7 个 check,tracer bullet |
| 1 | 1.7 | `tools/check_dashboard_writes.py` AD-21 lint(6→7 个 allowed write path) |
| 1 | 1.8 | `tools/_lint_helpers.py` —— 共享 `iter_python_files` + `parse_python_file` |
| 2 | 2.1 | `harness/migrate.py` —— SQLite WAL + schema_version 迁移框架 |
| 2 | 2.2 | `harness/artifact_store.py` + migration #2 `artifacts` 表 |
| 2 | 2.3 | `pipelines/software-v1@1.yaml` + `harness/pipeline_loader.py` —— AD-1/15/16 |
| 2 | 2.4 | `harness/project_manager.py` —— Project YAML 加载 + executor tuple 解析 |

> 之后 2.5-2.11 (Workflow Controller / Sample fixture / Gate engine / Acknowledgement store / Executor swap / Tracer bullet / Refactor) + Epic 3 (Error store / Regression set / Retry ladder / Skill bump / Benchmark) + Epic 4 (Cost guard / Herdr ingest / Dashboard / Final refactor) 都是 main 分支已有的。

---

## 1. 心智模型 — 30 秒能讲清

```
                        ┌─────────────────────────────────────────┐
                        │           控制平面 (harness/)            │
                        │                                           │
   project.yaml  ──►  Project Manager ──► Workflow Controller ──►  deliver.json
                        │       │                  │                  │
                        │       ▼                  ▼                  │
                        │  Artifact Store    Step Executor Adapter     │
                        │  (var/harness.    (human / Pi / OMP)         │
                        │   sqlite,                                  │
                        │   canonical)                                │
                        └─────────────────────────────────────────┘
                        四道不变式:
                        AD-17  sole canonical sha256 path     (harness.canonical)
                        AD-26  layer boundary                  (harness.ports allowlist)
                        AD-22  sole-writer per table           (artifact_store, registry, ...)
                        AD-4   append-only error store          (harness.error_store)
```

开发流程固定 (`software-v1@1` 写死六步),执行者可换。每次 run 把 6 个 step 的输出封成 **canonical sha256 寻址**的工件,产出 `delivery.json` 关单。

---

## 2. 目录里的"权威"文件

| 文件 | 是什么 | 何时碰它 |
|---|---|---|
| `pipelines/software-v1@1.yaml` | 六步定义 | 改六步时(只改这一个) |
| `var/projects/<id>/project.yaml` | 项目配置 | operator 改项目时 |
| `harness/canonical.py` | sole sha256 | **永不**碰(其他模块引用) |
| `harness/ports/__init__.py` | allowlist | 加新 port Protocol 时 |
| `harness/artifact_store.py` | sole writer of `artifacts` table | 加新表时加新 migration |
| `harness/migrate.py` | 迁移框架 | 加 migration #3, #4, ... |
| `harness/pipeline_loader.py` | sole writer of pipeline registry | 加新 pipeline 时 |
| `harness/project_manager.py` | sole writer of Project | 改 YAML schema 时 |
| `tools/check_layer_boundaries.py` | AD-26 边线 lint | 改 allowlist 时 |
| `tools/check_dashboard_writes.py` | AD-21 写路径 lint | 加新 write route 时 |
| `tools/_lint_helpers.py` | 共享 AST walking | 两个 lint 公共逻辑 |
| `harness/checks.py` | `check-baseline` 的 7 个 check | 改 baseline 契约时 |
| `harness/cli.py` + `__main__.py` | Typer CLI + `python -m harness` 入口 | 加新命令时 |

---

## 3. 5 个不变式(触碰前必读)

1. **AD-17: `harness.canonical` 是 sole sha256 path**
   - `from harness.canonical import canonical_bytes / canonical_sha256`,其他模块禁止 `import hashlib`
   - 工具: `tools/check_no_direct_sha256.py` (CI lint)
   - **违反代价:** 工件哈希两边算出来不一样 → audit-from-hashes 故事崩

2. **AD-26: `harness.ports.__all__` 是 layer 的唯一允许 import**
   - skills/agents/herdr/dashboard 下的 `.py` 只能 `from harness.ports import X`,X 必须在 `__all__` 里
   - 工具: `tools/check_layer_boundaries.py`
   - **违反代价:** Method / Execution 层穿透进控制平面

3. **AD-22: 每个"关键表"是 sole-writer**
   - `artifacts` 表 → 只有 `artifact_store`
   - `Skill Bump Registry` → 计划未来加
   - **违反代价:** 多写路径 → audit 故事不可信

4. **AD-4: 错误 / Event store 是 append-only**
   - 任何 record 写后不改
   - 工具: `tools/check_layer_boundaries.py` 不直接强制,但 schema 用 `INSERT`-only + PR review 卡
   - **违反代价:** UJ-3 audit-from-hashes 失效

5. **AD-1 + AD-15 + AD-16: Pipeline 不可变**
   - `software-v1@1.yaml` 启动时 load 进内存,运行时不可改
   - 升级 = 加 `@2` 文件,不 edit `@1`
   - **违反代价:** 跨 run 的 step 比较失效

---

## 4. 工件寻址协议(canonical sha256)

每个 step 的输出 = `lock(payload)` 返回的字符串 `sha256:<64hex>`,即:

```python
from harness.canonical import canonical_sha256
sha = canonical_sha256(payload)        # -> "sha256:abc...64hex"

# 跨调用 / 跨进程 / 跨机器 —— 完全相同
assert canonical_sha256(b'{"a": 1}') == canonical_sha256(b'{"a": 1}')
assert canonical_sha256(b'{"b": 1, "a": 2}') == canonical_sha256(b'{"a": 2, "b": 1}')  # JSON sort
```

`bytes` / `str` 走 text 路径(UTF-8 + LF 归一 + 末尾 LF),`bytes` 走 binary 路径(as-is)。
两个语义不同:**任何传 dict 的地方**走 JSON 排序路径,任何传 `b"..."` 的地方保持字节级。
`harness.artifact_store.put_pending({"k": 1})` 是 dict;**不要**传 `b'{"k": 1}'` 字面 JSON 字符串。

---

## 5. SQLite 迁移协议

```python
# 加新表 → append 一项 + 加 migration SQL
_MIGRATIONS = [
    (1, "init",              "CREATE TABLE _migrations (..."),
    (2, "add artifacts table", "CREATE TABLE artifacts (..."),
    (3, "add events table",    "CREATE TABLE run_events (..."),  # ← 新的
]
```

- `run_migrations(db)` 在 module import 时已校验 list(无重复版本 / 无 gap)
- `FutureSchemaVersion` 升级时升 harness 版本
- `MigrationCorrupted` sql_hash 校验时 DB 改过
- `_migrations` 表本身不可被其他模块写

**SQLite 路径**:`var/harness.sqlite` + WAL mode + foreign_keys=ON(默认 `harness.migrate.open_default_db()`)
**schema 演进**:v1 schema 整体保留;新表走新 migration,老表不要 ALTER
**bypass**:直接 `sqlite3 var/harness.sqlite` 可改数据,但 harness 下次启动会报 `MigrationCorrupted` 如果动了 `_migrations.sql_hash`

---

## 6. 项目 YAML contract(项目操作员视角)

`var/projects/<id>/project.yaml`:

```yaml
pipeline: software-v1      # 只允许这一个 (FR-1)
pipeline_version: 1        # 必须 >= 1
size: trivial              # trivial | session | epic | project —— 决定门禁是否强签字(FR-12)
steps:
  research:  { mode: human }
  design:    { mode: human }
  coding:    { mode: agent, agent: codex, model: gpt-5,
                          skills: [bmad-build@0.4.2] }   # skills 必须是 name@version
  testing:   { mode: human }
  review:    { mode: human }
  delivery:  { mode: human }
```

**严格性(plan 2.4 决定):**
- `mode: human` 必须**没有** agent / model(多余字段报错)
- `mode: agent` 必须有 agent + model + 非空 skills(任意字段缺失报错)
- skills 项必须 `name@version`,无版本 = `skill_pin_required`
- step 顺序错 = 自动重排 + `notes: ["reordered: ..."]`,不报错
- step 多于 6 步 = `unknown_step`
- 缺步 = `missing_step`
- pipeline 字段缺失 = `pipeline_required`
- pipeline 名不在 registry = `pipeline_not_found`

---

## 7. CLI 命令速查

(USER_MANUAL 有完整版本,这里只列 8 个 + 何时用)

| 命令 | 何时用 |
|---|---|
| `harness check-baseline` | 改 harness 代码后必跑(7 个 check 一次跑完) |
| `harness run <project>` | 一次跑完一个项目;首次跑 / 重跑 / 续跑都可用 |
| `harness swap <project> <step>` | 中途换执行者(AD-18,产生 `swap receipt` 记录) |
| `harness bench <step> --tier <size>` | 基准查询(>=3 runs 后返回推荐 tuple) |
| `harness cost-check` | 触发成本门禁(per-tier ceiling + Skill-bump 3× ceiling) |
| `harness cost-ack` | 解除成本暂停(operator 写 `cost_overrun_ack`) |
| `harness herdr-tail` | 拉 Herdr 事件(可选观测源) |
| `harness serve [--demo]` | 启动 dashboard(127.0.0.1:8137) |

`--help` 永远先跑。

---

## 8. 测试矩阵现状(commit 时 checklist)

- `uv run pytest` —— 全部 unit + integration,150+ tests,几秒跑完
- `uv run python -m harness check-baseline` —— 端到端 starter invariant,必须 8/8 OK
- `uv run python tools/check_layer_boundaries.py` —— AD-26
- `uv run python tools/check_dashboard_writes.py` —— AD-21
- `uv run python tools/check_terminal_status.py` —— AD-24 (one status resolver)
- `uv run python tools/check_no_direct_sha256.py` —— AD-17

前 4 项跑通,后 2 项是新加的没本 session 经手。

---

## 9. CI 入口

`.github/workflows/` 跑 `uv run pytest` + `uv run harness check-baseline` + 4 个 lint。
`pyproject.toml` 锁依赖: `uv lock --check` 必须在干净 clone 上 exit 0。
**`var/` 不 commit**:`.gitignore` 排除 `var/secrets/harness.key` + `var/harness.sqlite*` + `var/herdr_mirror.sqlite*` + `var/herdr/stream.jsonl`。
骨架 marker 留下:`var/<layer>/.gitkeep` + `var/secrets/.gitkeep` 让 dir 在 git 里存在。

---

## 10. 这个 session 跳过的 — 后续 story 必读

我没经手但 main 上已合入的代码:

- **`harness.workflow_controller`** (Story 2.5):核心状态机,6 步 routing + `step_status()` 单 resolver(AD-24)
- **`harness.gate_engine`** (Story 2.7):per-step contract gate(每步必走 verifier 才 `Locked`)
- **`harness.acknowledgement_store`** (Story 2.8):AD-23 path-triple signed writer
- **`harness.executor_swap`** (Story 2.9):AD-18 `project_edit_lock` + 跨调用幂等
- **`harness.tracer_bullet`** (Story 2.10):`harness run` + `swap` + `delivery.json` 端到端
- **`harness.error_store` / `harness.retry_ladder` / `harness.skill_bump_registry`** (Epic 3)
- **`harness.cost_ledger` / `harness.cost_guard` / `harness.herdr_ingest`** (Epic 4 partial)
- **Operator Dashboard**:Bun + vanilla TS SPA + FastAPI read model

每个都是 `harness/` 下的新 module,遵循"sole-writer" / "canonical sha256" / "frozen dataclass" 三条主线。

---

## 11. 返工 checklist — "我加新 X 时,先问 5 问"

| 加什么 | 问 1: sole writer 是谁? | 问 2: 走 canonical sha256 吗? | 问 3: 走 migrate 吗? | 问 4: 跨 layers 暴露? | 问 5: 入口 CLI? |
|---|---|---|---|---|---|
| 新 step 类型的 artifact | artifact_store | 是(走 payload 字段) | 否(同 artifacts 表) | AD-26 否 | `harness run` 已含 |
| 新 pipeline(`software-v2@1`) | pipeline_loader(register) | 是(走 contract 名) | 否 | AD-26 否 | `harness run` 自动解析 |
| 新 Adapter(例如 OMP) | executor.py(register) | 是(走 capability) | 否 | AD-26 否 | import `harness.adapters.omp` 即注册 |
| 新 canonical hash 用法(不用 hashlib) | 不需要 | 是,加到 canonical.py | 否 | 否 | 不需要 CLI |
| 新 dashboard write path | dashboard/main.py | 是(走 signature) | 否 | AD-21 allowlist | `cost-ack` 模式 |
| 新 SQLite 表 | migrate.py append migration | 是(走 payload/row) | 是,加 migration #N | AD-26 否 | 看是否需要 CLI |
| 新 BMAD skill 引用 | project YAML 写 `name@version` | 是(skill pin) | 否 | 否 | `harness run` 自动 |
| 新 BMAD skill 安装 | `var/skills/<name>@<version>/` | 不需要 | 否 | AD-26 允许(目录在 layer) | `harness run` 自动 |

---

## 12. 自我 review — 我可能留的"债务"

1. **`acknowledgements/my-first/` 是 untracked**—— 之前某次 test run 留下的 evidence(目录有 demo-1 的 6 个 step acknowledgement files)。要么 commit 当 demo 用例,要么 gitignore + clean。我倾向**保留并 commit**,因为它是 "一个完成的 run 长什么样" 的实物。
2. **`harness/adapters/` 只有一个 human.py** —— OMP/Pi/Codex adapter 没写,OQ-6 仍 open
3. **`pipelines/software-v1@1.yaml` 没加 `bmadrun.<step>.v1` 之外的 contract** —— 等待 2.7 的 contract registry 落地
4. **CI workflow 文件没在 session 范围** —— main 上有但我没经手

---

## 13. 一行总结

**"Harness owns state, agents own execution, sha256 owns identity."**
改状态 → harness/checks.py 或 cli.py;
改执行 → harness/adapters/ 加新文件;
改身份 → harness/canonical.py 唯一;
改契约 → harness/ports/__all__ + project YAML。
其他都是 plumbing。
