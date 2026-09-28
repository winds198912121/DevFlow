# DevFlow Harness — 使用手册

> GitHub：**https://github.com/winds198912121/DevFlow**（branch: `master`）
> 本地路径：`/Users/winds/Downloads/DevFlow`

---

## 1. 这是什么

DevFlow 是一个 **AI 开发平台的控制平面（harness）**。

核心思路：开发流程固定，执行者可变。

```
research → design → coding → testing → review → delivery
   ↑ 这六步的顺序写死在代码里（AD-15），不可配置
   ↑ 每一步背后的「谁来做」（agent / LLM / skills）可随时替换并基准测试
```

- **harness/** — 控制平面本体（状态机、工件、门禁、成本、基准）
- **dashboard/** — 操作员仪表盘（TypeScript SPA + FastAPI 读模型）
- **agents/** — 执行器适配器（human 已实现）
- **skills/** — BMAD 方法层，按项目 YAML 固定版本
- **herdr/** — 可选的进程外观测源（**只是参考信息，永不权威**，AD-9/AD-19）

价值在于：换掉某一步的执行者后，能用**同一套回归集**量化它是否更好，且所有状态变更都有签名与审计。

### 运行流程（四张图）

![六步流水线总览](img/devflow-flow-pipeline.png)

**① 六步流水线。** `project.yaml` 经 Project Manager 校验后交给 Workflow Controller；
每个步骤由适配器执行、把结果封存成工件、并写一个 `.locked` 标记——该标记同时是
下一步骤的前置条件。`size` 决定门禁是否强制：`epic`/`project` 需要签名裁决
（`Locked`），`trivial`/`session` 直接跳过门禁（`Done`）。

![单个步骤的生命周期](img/devflow-flow-step.png)

**② 单个步骤的判定顺序。** 三道判定都在动适配器之前完成：跨调用幂等（`.locked`
标记已存在就直接复用，不重跑适配器）、前置步骤必须已封存（AD-15）、适配器必须返回
`succeeded`。三个判定各有自己的中止出口。

> **最容易搞混的一点**：前置条件问的是「**上一步的工件封存了吗**」，
> **不是**「上一步裁决了吗」——这是两个不同的问题。

![步骤终态及其转移](img/devflow-flow-states.png)

**③ 四个终态。** `Done` 与 `Locked` 是不同的终态（AD-11）：前者表示门禁被**跳过**
（`trivial`/`session` 档），后者表示门禁被**通过**（有签名裁决）。
`Failed` 表示裁决是 `rejected`。

![失败路径与重试阶梯](img/devflow-flow-failure.png)

**④ 失败与重试阶梯。** 失败先记一条只增不改的 Error Store 记录（AD-4），再逐级升档：
同执行者重试 → 换 LLM → 换 agent → 用已晋级的 skill；第五档交回人工并暂停，不再自动推进。

> 矢量版：`docs/img/*.svg`（同名）。网页版：`docs/devflow-flow.html`（单文件、离线可开）。
> 重新导出：`uv run python tools/export_flow_diagrams.py`（`--scale 3` 出印刷尺寸）。

---

## 2. 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | `>=3.12.10,<3.13` | `pyproject.toml` 硬约束 |
| uv | 任意较新版本 | 依赖与虚拟环境管理 |
| Bun | **1.4.2** | 仅仪表盘 SPA 需要；缺失时相关测试自动 skip |

---

## 3. 安装

```bash
cd /Users/winds/Downloads/DevFlow

uv sync                     # 创建 .venv 并装依赖
uv lock --check             # 校验 lockfile 一致
uv run harness --help       # 应列出 8 个子命令

# 仪表盘 SPA（可选，但要看到界面就得装）
cd dashboard && bun install && bun run build && cd ..
```

验证安装：

```bash
uv run python -m harness check-baseline
# baseline: 8/8 OK | ... | 8 paths present
```

---

## 4. 五分钟上手

```bash
# 1. 灌入演示数据（python-hello 项目 + 4 条回归记录 + 成本记录 + Herdr 事件）
uv run harness serve --demo

# 2. 启动仪表盘
uv run harness serve
#    → dashboard: http://127.0.0.1:8137/   (API docs: /docs)

# 3. 换一个终端，跑一次完整流程
uv run harness run --project tests/fixtures/sample-projects/python-hello --run-id R1

# 4. 查询基准
uv run harness bench --step coding --tier trivial --contract v1
#    → bench OK: ... metric_summary=0.915 contributing_runs=4
```

刷新浏览器，四个视图都能看到真实数据。

---

## 5. 项目 YAML 写法

项目定义在 `var/projects/<project_id>/project.yaml`。

### 最小可用（human 模式）

```yaml
pipeline: software-v1        # 必填，字符串
pipeline_version: 1          # 可选，默认 1，正整数
size: trivial                # 可选，默认 session；trivial|session|epic|project
steps:
  research:
    mode: human
  design:
    mode: human
  coding:
    mode: human
  testing:
    mode: human
  review:
    mode: human
  delivery:
    mode: human
```

### agent 模式

```yaml
steps:
  coding:
    mode: agent
    agent: claude            # 必填，非空
    model: opus              # 必填，非空
    skills:                  # 必填，非空，且每个都必须锁版本 name@version
      - bmad-build@0.4.2
```

### 规则（违反会直接报错，不是警告）

| 字段 | 规则 | 错误码 |
|---|---|---|
| `pipeline` | 必填，字符串 | `pipeline_required` |
| `size` | 必须是 `trivial\|session\|epic\|project` | `project_yaml_parse_error` |
| `mode` | 必须是 `human\|agent` | `invalid_executor_tuple` |
| `mode: human` | **禁止**出现 `agent` / `model` | `invalid_executor_tuple` |
| `mode: agent` | `agent`、`model`、`skills[]` 都必填非空 | `invalid_executor_tuple` |
| `skills[]` | 每项必须 `name@version` 形式 | `skill_pin_required` |
| 六个步骤 | 必须六个都在、名字与顺序固定 | `unknown_step` |

**`size` 的影响（很重要）：**

- `trivial` / `session` → **跳过门禁**，步骤直接 `Done`（FR-12）
- `epic` / `project` → 门禁强制，步骤在拿到 Acknowledgement 前是 `Pending`

---

## 6. 命令参考

全部 8 个命令。`uv run harness <cmd> --help` 可看实时帮助。

### `check-baseline` — 基线自检

```bash
uv run harness check-baseline
```
跑 8 项不变量检查（签名密钥、规范化、签名往返、3 个 CI lint、适配器、目录骨架）。全绿退出 0。

### `run` — 端到端跑完六步

```bash
uv run harness run --project <路径或项目ID> [--run-id <ID>] [--inject-failure-at <步骤>]
```

| 参数 | 说明 |
|---|---|
| `--project` / `-p` | **必填**。项目 YAML 目录，或 `var/projects/` 下的 project_id |
| `--run-id` / `-r` | 复用既有 run_id；跨调用幂等（重复跑不会重做已封存的步骤） |
| `--inject-failure-at` | 在该步骤注入一次人为故障，走**重试阶梯**后继续；**进程仍退出 0** |

**注意**：`--inject-failure-at` 的值必须是六个步骤名之一，否则报 `unknown_step` 并退出 2。

**⚠️ human 模式需要 stdin。** 非交互场景要喂输入：

```bash
yes x | uv run harness run --project tests/fixtures/sample-projects/python-hello --run-id R1
```

不给 stdin 会在第一步就失败：`executor_invocation_failed: ... operator_input_eof`。

### `swap` — 中途替换执行者（AD-18）

```bash
uv run harness swap --project <ID> --prev '<JSON>' --new '<JSON>' [--by <人>] [--intent <说明>]
```

在 `project_edit_lock` 保护下记录一次替换凭据，产出 `prev_yaml_hash` / `new_yaml_hash`。
`--prev` 与 `--new` 不能相同，否则 `swap_refused`；别人持锁则 `project_locked`。

### `bench` — 基准查询

```bash
uv run harness bench --step <步骤> [--tier <档>] [--contract <版本>] [--k <下限>]
```

默认 `--tier trivial`、`--k 3`。可比运行数不足时 `regression_set_insufficient`（退出 1）。

### `cost-check` — 成本门禁（AD-8）

```bash
uv run harness cost-check --project <ID> [--tier <档>]
```

超过该档上限返回 `pause` 并**退出 1**，同时写入暂停标记。

### `cost-ack` — 操作员解除暂停

```bash
uv run harness cost-ack --project <ID>
```

### `herdr-tail` — 拉取 Herdr 事件

```bash
uv run harness herdr-tail
```

把 `var/herdr/stream.jsonl` 的新事件镜像进 `var/herdr_mirror.sqlite`。
**流文件不存在时静默返回 0**（Herdr 宕机不得阻塞 harness，NFR-Reliab-2）。
**遇到坏行**：抛出 `MalformedHerdrEvent`，但**已消费的偏移量会前移并提交**——所以坏行不会卡死后续事件，再调一次即可继续。

### `serve` — 启动仪表盘

```bash
uv run harness serve [--demo] [--host 127.0.0.1] [--port 8137]
```

| 模式 | 行为 |
|---|---|
| `serve` | 启动服务：`http://127.0.0.1:8137/`（SPA）+ `/docs`（API 文档） |
| `serve --demo` | 只灌演示数据并**退出**（不启服务），可安全脚本化调用 |

`dashboard/dist` 不存在时只服务 API，并提示你去 `dashboard/` 里 `bun run build`。

---

## 7. 操作员仪表盘

启动后访问 `http://127.0.0.1:8137/`。

### 四个视图

| 视图 | 内容 | 对应需求 |
|---|---|---|
| **Run status** | 各步骤终态（`Done`/`Locked`/`Pending`/`Failed`）+ 门禁模式 | FR-24 |
| **Error store** | 错误清单 + 分页 + 6 维过滤 | FR-25 |
| **Regression diff** | 技能升级回归的逐步骤通过/失败 + 可比性标记 | FR-18 |
| **Benchmark output** | 推荐指标、指标值、贡献运行列表（含哈希） | FR-21 |

### 过滤（Error store）

支持按 `run_id`、`step`、`category`、`executor_tuple`、`since`、`until` 过滤。

- 多个过滤条件是 **AND**，不是 OR
- 不填 = 返回该项目的全部错误
- `category` 必须是闭集之一，否则 `category_not_found`（**不会静默返回空**）
- 过滤键**拼错会被拒绝**（`unknown_filter`），不会静默忽略

### 写入路径（只有 7 个）

仪表盘的写操作是**闭集**（AD-21）。第 8 个写路由会让 CI 失败。

| 方法 | 路径 |
|---|---|
| POST | `/acknowledgements` |
| POST | `/swap-executor` |
| POST | `/skill-bump-regression` |
| POST | `/skill-bump-promote` |
| POST | `/cost-overrun-ack` |
| POST | `/regression-set-remove` |
| POST | `/project-edit-lock` |

**每个写操作都必须带签名**，请求头 `X-Harness-Signature: <hex>`，签名对象是请求体 JSON 本身。缺失或不匹配 → **401**。

```bash
# 例：给一个暂停的项目做成本确认
uv run python - <<'PY'
from harness.signing import sign
import httpx

body = {"project_id": "python-hello"}
r = httpx.post("http://127.0.0.1:8137/cost-overrun-ack",
               json=body,
               headers={"X-Harness-Signature": sign(body).hex()})
print(r.status_code, r.json())
PY
```

> 签名对象是**请求体里的那个 JSON 对象本身**（不是字符串）。
> 服务端用 `json.loads(请求体)` 得到同一个 dict 再验签，所以键顺序无所谓，但**字段必须一模一样**——
> 改一个值签名就失效（401）。

### 状态码约定

| 码 | 含义 | 例子 |
|---|---|---|
| 400 | 参数语义错误 | `category_not_found`、`unknown_filter` |
| 401 | 签名缺失/无效 | `invalid_harness_signature` |
| 404 | 对象不存在 | `run_not_found`、`bump_not_found`、`project_not_found` |
| 409 | 状态冲突 | `project_edit_lock_held`、`regression_set_insufficient`、`run_ambiguous` |
| 422 | 内容不可用 | `project_yaml_invalid` |

---

## 8. 目录与数据布局

```
harness/          控制平面（Python）
  ports/          对外发布的唯一接口面（AD-26）
  migrate.py      唯一的 schema 定义源
dashboard/
  src/            SPA 源码（4 视图 + API 客户端）
  dist/           构建产物，被 FastAPI 挂到 /
pipelines/        software-v1@1.yaml（不可变，AD-1）
tools/            CI lint + 组装根
tests/            测试
var/              运行时数据（**不进 git**）
  projects/<id>/project.yaml
  projects/<id>/runs/<run_id>/<step>/
  harness.sqlite      错误/回归集/技能升级/成本
  devflow.sqlite      运行事件/编辑锁
  secrets/harness.key 签名私钥（0600）
```

---

## 9. 测试与 CI 检查

```bash
# Python（336 个用例）
uv run pytest

# 前端
cd dashboard
bun test              # 17 个视图测试
bunx tsc --noEmit     # 类型检查
bun run build         # 产出 dist/

# 4 个 CI lint（必须从项目根运行）
uv run python tools/check_layer_boundaries.py    # AD-26 依赖方向
uv run python tools/check_dashboard_writes.py    # AD-21 写路由白名单
uv run python tools/check_terminal_status.py     # AD-24 单一状态解析器
uv run python tools/check_no_direct_sha256.py    # AD-17 只能经 canonical 哈希
```

全绿 = 退出 0。`check-baseline` 会把前 3 个 lint 一起跑。

---

## 10. 改代码前必读：几条硬约束

这些不是建议，是 **CI 会拦你的规则**。

| 规则 | 内容 | 校验方式 |
|---|---|---|
| **AD-26** | `skills/` `agents/` `herdr/` `dashboard/` 下的 Python **只能** 从 `harness.ports` 导入 harness；命名空间必须出现在 `harness/ports/__init__.py` 的 `__all__` | `check_layer_boundaries.py` |
| **AD-21** | 仪表盘写路由只能是那 7 个 | `check_dashboard_writes.py` |
| **AD-24** | 步骤终态只能由 `harness.workflow_controller.step_status` 解析。视图可以渲染 *输出*（`terminal`、`gate_mode`），**不能读输入**（`verdict`、`outcome`、`confirm_id`、`acknowledgement_id`） | `check_terminal_status.py` |
| **AD-17** | 哈希只能走 `harness.canonical`，禁止直接 `import hashlib` | `check_no_direct_sha256.py` |
| **AD-15** | 六步顺序写死，改 `pipelines/*.yaml` 的顺序会在启动时抛错 | 启动期校验 |
| **AD-4 / AD-3 / AD-7** | 错误记录、工件、回归集**只增不改** | 写入 API 拒绝覆盖 |

**改 schema 的唯一正确姿势**：在 `harness/migrate.py` 的 `_MIGRATIONS` 里加一条迁移。各 store 的 `_ensure_table` 会**自动**从那里取 DDL（`migrate.ensure_tables`），不要再手抄一份 `CREATE TABLE`。

---

## 11. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `harness run` 挂在等待输入 | human 适配器要 stdin，用 `yes x \| uv run harness run ...` |
| `operator_input_eof` | 同上，stdin 被关掉了 |
| `project_not_found` | `--project` 给的路径既不是含 `project.yaml` 的目录，也不是 `var/projects/` 下的 ID |
| `unknown_step` | 步骤名必须是六个之一；`--inject-failure-at` 也受此约束 |
| `regression_set_insufficient` | 可比运行数不到 `--k`（默认 3）。先 `serve --demo` 灌数据 |
| `project_locked` / `project_edit_lock_held` | 有别人持编辑锁；锁 5 分钟自动过期，或等对方释放 |
| `category_not_found` | `category` 拼写不在闭集里（闭集见 `harness/error_store.py`） |
| 浏览器打开是 API 报错不是界面 | `dashboard/dist` 没构建：`cd dashboard && bun install && bun run build` |
| 页面能开但点过滤报 `missing element` | 不该再发生（已加启动自检）；若出现，说明 `index.html` 的 id 与 `src/main.ts` 的 `REQUIRED_ELEMENTS` 不一致 |
| 仪表盘没数据 | 先 `uv run harness serve --demo`，再跑一次 `harness run` 造出 run 目录 |
| 跑完 pytest 后 demo 数据没了 | 部分测试会重置 `var/harness.sqlite`（共享真实路径），重新 `serve --demo` 即可 |

---

## 12. 已知限制（v1 范围）

- **单机自托管**。多节点 / k8s / serverless 留待 v2
- **只有 human 适配器**。`agents/` 下其余适配器（pi / omp / codex / claude_code / dsh）未实现
- **Herdr 发射端未实现**。当前只有 harness 侧的接收与镜像路径
- **重试阶梯没有自动触发点**。`retry_ladder.advance` 目前唯一的非测试调用者是 `harness run --inject-failure-at`；阶梯不会在真实步骤失败时自动介入
- **仪表盘写操作靠调用方自行签名**，没有内置 CLI 封装（用上面的 Python 片段）
- **AD-25 的 Acknowledgement 表单未实现**（三值裁决枚举的 UI 呈现）
- `harness run` 走的是内存库 + 磁盘目录，六步之外没接入成本/门禁的自动联动

---

## 13. 路线与记录在哪

| 想知道 | 看这里 |
|---|---|
| 每个决策的理由 | `_bmad-output/planning-artifacts/architecture/ARCHITECTURE-SPINE.md`（27 条 AD） |
| 每个故事做了什么、改了什么 | `_bmad-output/preview-ticketing/initiative-devflow-harness/*/story-*-plan.md` |
| 机器可读契约 | `_bmad-output/specs/spec-devflow/` |
| 提交历史 | `git log --oneline` |
