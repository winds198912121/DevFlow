# DevFlow Harness — 端到端示例 (End-to-End Examples)

> 配套 USER_MANUAL.md 的命令参考;本文档是**实际能跑**的最小例子集合。
> 所有命令在 repo 根目录 `/Users/winds/Downloads/DevFlow` 下用 `uv run` 执行。

---

## 0. 前置

```bash
# 一次性安装(已经做过就跳过)
uv sync
uv lock --check                       # 必须 exit 0,证明 lockfile bit-identical
```

**预期产出:** `uv lock --check` 安静退出 0。

---

## 1. 基线自检(改代码后必跑)

```bash
uv run python -m harness check-baseline
```

**预期产出(单行 summary):**

```
baseline: 8/8 OK | /path/var/secrets/harness.key mode=0o600 size=64 | 
surface ok (empty digest sha256:e3b0c44298fc1...) | sign+verify roundtrip ok | 
clean | clean | clean | 1 adapter(s): human | 8 paths present
```

`8/8` 表示 8 个 check 全过(6 个原始 + check_dashboard_writes + check_terminal_status)。
任何一项 fail,summary 仍打印 `M/8 OK` 加 `first failure: <name>: <detail>` 到 stderr;CLI exit 1。

---

## 2. CI 四个 lint(改 harness/ 或 contracts/ 后跑)

```bash
uv run python tools/check_layer_boundaries.py    # AD-26
uv run python tools/check_dashboard_writes.py    # AD-21
uv run python tools/check_terminal_status.py     # AD-24
uv run python tools/check_no_direct_sha256.py    # AD-17
```

每个 exit 0 = clean; exit 1 + 一行 `prefix: <file>:<lineno> <detail>` = violation。
**这 4 个必须从项目根目录跑**(`tools._lint_helpers` 用 namespace package 解析)。

---

## 3. happy path 端到端跑一个项目

项目 `var/projects/python-hello/project.yaml` 已 ship,6 步全 `mode: human`、`size: trivial`。

**用管道喂 6 个 operator input(每个 step 一个):**

```bash
printf 'research done\ndesign done\ncode done\ntests pass\nreview approved\ndelivery ready\n' \
  | uv run harness run --project python-hello --run-id my-first-run
```

**预期产出:**

```
[harness/human] capability=research — operator input: [harness/human] capability=design — 
operator input: [harness/human] capability=coding — operator input: 
[harness/human] capability=testing — operator input: [harness/human] 
capability=review — operator input: [harness/human] capability=delivery — 
operator input: harness run: project_id=python-hello run_id=my-first-run steps=6 OK
```

**看产出:**

```bash
ls var/projects/python-hello/runs/my-first-run/
# coding  delivery  delivery.json  design  research  review  testing

cat var/projects/python-hello/runs/my-first-run/delivery.json | python -m json.tool
```

**预期 `delivery.json` 字段:**
- `project_id`: `python-hello`
- `run_id`: `my-first-run`
- `delivered_at`: ISO 8601 UTC
- `executor_tuple_hash`: `sha256:<64hex>`(整个 run 的执行者组合)
- `signature`: 整个 delivery 的 Ed25519 签
- `total_artifacts`: 6 个 step 的 sha256(工件寻址)
- `total_acknowledgements`: 6 个 step 的 sha256(签名裁决)

**6 步各自的 Acknowledgement 落在 `acknowledgements/<run_id>/<step>` 下**(单独的目录,不是 `var/projects/.../runs/<run_id>/<step>/`,因为 acknowledgement 是 runner-wide record)。

---

## 4. Retry ladder 演示(失败走 5 级阶梯)

`--inject-failure-at` 注入一个人造失败,演示 FR-15 的 5-rung ladder:

```bash
printf 'research done\ndesign done\ncode done\ntests pass\nreview approved\ndelivery ready\n' \
  | uv run harness run --project python-hello --run-id demo-inject --inject-failure-at coding
```

**预期产出(关键行):**

```
...
injected failure at coding: rung 2 result=fail error_record=<ULID>
...
harness run: project_id=python-hello run_id=demo-inject steps=6 OK
```

- 走完 rung 2(同 Agent + 换 LLM)失败 → 继续走 rung 3/4
- Run 仍 exit 0(ladder 吸收失败,不 abort run)
- 错误记录存进 `var/projects/python-hello/runs/demo-inject/run_event_log` 的 error record(由 AD-4 append-only ledger 持有)

---

## 5. 成本门禁(per-tier ceiling)

```bash
uv run harness cost-check --project python-hello
```

**预期产出:**

```
cost_check: project=python-hello tier=trivial decision=continue
```

`decision=continue` 表示当前 run 的 token 累计 < trivial tier ceiling(5e5 tokens,Story 4.1)。
`decision=pause` 表示已超 ceiling,需要 `harness cost-ack --project python-hello` 解暂停。

---

## 6. 基准查询(>=3 runs 后)

```bash
uv run harness bench --step coding --tier trivial
```

**预期产出:**

```
bench OK: step=coding tier=trivial contract=v1 metric_summary=0.915 contributing_runs=4
```

- `metric_summary`: 当前用 `acceptance_coverage.fr_passed / fr_total`(Story 3.4 的默认 metric)
- `contributing_runs`: 比较集里的 runs 数(< 3 会报 `regression_set_insufficient`,因为 NFR-Reliab-3)

**示例来自 Story 3.8 sample regression set 的 4 个 deterministic runs on python-hello。**

---

## 7. 中途换执行者(AD-18,需要 project_edit_lock)

```bash
# Edit var/projects/python-hello/project.yaml 把 coding step 从 mode: human 换成 mode: agent
# 然后:
uv run harness swap --project python-hello --run-id R1 --step coding
```

预期:**拒 `project_edit_lock` 之外的所有写**(AD-21 allowlist),只放行这 7 个 POST 路径:
- `/acknowledgements`
- `/swap-executor`
- `/skill-bump-regression`
- `/skill-bump-promote`
- `/cost-overrun-ack`
- `/regression-set-remove`
- `/project-edit-lock`

(本例假设你的当前 run_id 还没 archive;实际行为是产生一条 swap receipt 并写 Acknowledgement。)

---

## 8. 操作员仪表盘

```bash
uv run harness serve --demo   # 种 demo 数据(python-hello + 4-run regression set)
```

打开 <http://127.0.0.1:8137/> 看 4 个 view:
- **run-status**:6 步状态 + 6 个 sha256 + 6 个 executor tuple
- **error-store**:可按 `category=skill` 等过滤
- **regression-diff**:Skill bump 每次的 per-step pass/fail
- **benchmark**:recommendation + metric + contributing runs

(无需 `--demo` 也行;用真实 run 数据。)

---

## 9. 完整 round-trip(给同事演示用)

```bash
# 1. 干净状态确认
uv run python -m harness check-baseline

# 2. 端到端跑
printf 'research done\ndesign done\ncode done\ntests pass\nreview approved\ndelivery ready\n' \
  | uv run harness run --project python-hello --run-id demo-roundtrip

# 3. 看交付物
cat var/projects/python-hello/runs/demo-roundtrip/delivery.json | python -m json.tool

# 4. 跑基准
uv run harness bench --step coding --tier trivial

# 5. 跑成本门禁
uv run harness cost-check --project python-hello

# 6. 重跑 baseline
uv run python -m harness check-baseline
# 期望: 8/8 OK(每次 run 之后 baseline 不变,因为 check-baseline 不读 runs/)

# 7. 启动 dashboard
uv run harness serve --demo
# → http://127.0.0.1:8137/
```

---

## 10. 故障排查 cheat sheet

| 症状 | 看哪里 | 常见 fix |
|---|---|---|
| `check-baseline` 报 `first failure: canonical_path: ...` | `uv run python -c "from harness.canonical import canonical_bytes, canonical_sha256; print('OK')"` | Python 3.12+ / PEP 686 源文件 NFKC 化会让字面 `'\u00e9\u0301'` 在 tokenize 时已是 NFC |
| `check_layer_boundaries` 报 `harness.<x>` 在 skills/agents/herdr/dashboard/ | lint 抓出 import 越界 | 加 `name@version` 到 `harness/ports/__init__.py` 的 `__all__` |
| `harness run` 卡在 `[harness/human] capability=...` | stdin 没数据 | 喂管道或 interactive 输入(空字符串 = EOF) |
| `harness run` 报 `pipeline_not_found` | `var/projects/<id>/project.yaml` 里 `pipeline:` 字段 | 必须是 `software-v1`(唯一 v1 pipeline) |
| `migration_corrupted: version N ...` | DB 里的 `_migrations.sql_hash` 与代码里的 SQL hash 不一致 | 删 `var/harness.sqlite` 让 harness 重新从空建(丢掉未备份数据) |
| `acknowledgements/my-first/` 是 untracked | 上次 run 留下的 evidence | `git add acknowledgements/` commit,或加到 `.gitignore` |
