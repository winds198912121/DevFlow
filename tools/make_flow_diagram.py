#!/usr/bin/env python3
"""Generate docs/devflow-flow.html — the DevFlow runtime flow as editorial diagrams.

Emits four figures under the pi.dev-derived skin in
`~/.agents/skills/diagram-design/references/style-guide.md`:
  1. the six-step pipeline (flowchart, macro)
  2. one step's lifecycle (flowchart, the real logic)
  3. step terminal states (state machine, AD-11/AD-24)
  4. the failure path + retry ladder

Geometry is generated rather than hand-written so every coordinate stays on the
4px grid and every connector is a rounded right-angle elbow (SKILL.md §6 rules
1-6). Run with the project venv:

    uv run python tools/make_flow_diagram.py
"""

from __future__ import annotations

from pathlib import Path

# --- Skin (style-guide.md, pi.dev derivation, light) -----------------------
PAPER = "#f3f2f0"
PAPER2 = "#ebe7e4"
INK = "#252f3d"
MUTED = "#5c5752"
SOFT = "#8b847d"
ACCENT = "#b86b52"
ACCENT_TINT = "rgba(184,107,82,0.08)"
LINK = "#4b607c"
RULE = "rgba(37,47,61,0.12)"

SERIF = "'Plantin MT Pro', 'Plantin MT Std', Plantin, Georgia, serif"
MONO = ("'Commit Mono', ui-monospace, 'SF Mono', Menlo, "
        "'PingFang SC', 'Hiragino Sans GB', monospace")

R = 8  # elbow radius

#: Shapes and connector endpoints, filled as each figure is built.
#:   ("rect", x0, y0, x1, y1) | ("diamond", cx, cy, hw, hh) | ("ring", cx, cy, r)
SHAPES: list[tuple] = []
ARROWS: list[tuple[float, float]] = []
LABELS: list[tuple[float, float, float, float]] = []


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --- Primitives ------------------------------------------------------------

def box(x, y, w, h, lines, *, fill="#ffffff", stroke=INK, rx=6,
        tag=None, tag_stroke=None, dash=None, name_size=12, sub_size=9):
    """A node box: opaque paper mask, styled rect, optional tag, name, sublabel."""
    SHAPES.append(("rect", x, y, x + w, y + h))
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{PAPER}"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1"'
        + (f' stroke-dasharray="{dash}"' if dash else "") + "/>",
    ]
    if tag:
        ts = tag_stroke or stroke
        out.append(
            f'<rect x="{x + 8}" y="{y + 6}" width="{8 * len(tag) + 12}" height="12" rx="2" '
            f'fill="transparent" stroke="{ts}" stroke-opacity="0.4" stroke-width="0.8"/>'
        )
        out.append(
            f'<text x="{x + 14 + 4 * len(tag)}" y="{y + 15}" fill="{ts}" fill-opacity="0.85" '
            f'font-size="7" font-family="{MONO}" text-anchor="middle" '
            f'letter-spacing="0.08em">{esc(tag)}</text>'
        )
    cx = x + w / 2
    top = y + (22 if tag else 0)
    n = len(lines)
    block = n * 18
    start = top + (h - (22 if tag else 0) - block) / 2 + 13
    for i, ln in enumerate(lines):
        size = name_size if i == 0 else sub_size
        family = MONO if i > 0 else MONO
        weight = "600" if i == 0 else "400"
        color = INK if i == 0 else MUTED
        out.append(
            f'<text x="{cx}" y="{start + i * 18:.0f}" fill="{color}" font-size="{size}" '
            f'font-weight="{weight}" font-family="{family}" '
            f'text-anchor="middle">{esc(ln)}</text>'
        )
    return "\n".join(out)


def oval(cx, y, w, h, lines):
    x = cx - w / 2
    SHAPES.append(("rect", x, y, x + w, y + h))
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{PAPER}"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" '
        f'fill="{PAPER2}" stroke="{MUTED}" stroke-width="1"/>',
        f'<text x="{cx}" y="{y + h / 2 + 4}" fill="{INK}" font-size="12" font-weight="600" '
        f'font-family="{MONO}" text-anchor="middle">{esc(lines[0])}</text>',
    ]
    return "\n".join(out)


def diamond(cx, cy, hw, hh, lines, *, stroke=INK, fill="#ffffff"):
    SHAPES.append(("diamond", cx, cy, hw, hh))
    pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
    out = [
        f'<polygon points="{pts}" fill="{PAPER}"/>',
        f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>',
    ]
    if len(lines) == 1:
        out.append(
            f'<text x="{cx}" y="{cy + 4}" fill="{INK}" font-size="12" font-weight="600" '
            f'font-family="{MONO}" text-anchor="middle">{esc(lines[0])}</text>'
        )
    else:
        out.append(
            f'<text x="{cx}" y="{cy - 2}" fill="{INK}" font-size="12" font-weight="600" '
            f'font-family="{MONO}" text-anchor="middle">{esc(lines[0])}</text>'
        )
        out.append(
            f'<text x="{cx}" y="{cy + 15}" fill="{MUTED}" font-size="9" '
            f'font-family="{MONO}" text-anchor="middle">{esc(lines[1])}</text>'
        )
    return "\n".join(out)


def arrow(d, *, color=None, dash=None, marker="arrow"):
    ARROWS.append(_endpoint(d))
    c = color or MUTED
    return (
        f'<path d="{d}" fill="none" stroke="{c}" stroke-width="1.1"'
        + (f' stroke-dasharray="{dash}"' if dash else "")
        + f' marker-end="url(#{marker})"/>'
    )


def straight(x1, y1, x2, y2, **kw):
    """Straight connector — only legal when endpoints share x or y."""
    assert x1 == x2 or y1 == y2, f"diagonal connector ({x1},{y1})->({x2},{y2})"
    return arrow(f"M {x1} {y1} L {x2} {y2}", **kw)


def elbow_down_then_side(x1, y1, x2, y2, **kw):
    """Down from (x1,y1), then horizontally to x2, arriving at (x2,y2)."""
    sign = 1 if x2 > x1 else -1
    return arrow(
        f"M {x1} {y1} V {y2 - R} Q {x1} {y2} {x1 + sign * R} {y2} "
        f"H {x2 - sign * 0}",
        **kw,
    )


def elbow_side_then_down(x1, y1, x2, y2, **kw):
    """Horizontally from (x1,y1) to x2, then down to (x2,y2)."""
    sign = 1 if y2 > y1 else -1
    return arrow(
        f"M {x1} {y1} H {x2 - R if x2 > x1 else x2 + R} "
        f"Q {x2} {y1} {x2} {y1 + sign * R} V {y2}",
        **kw,
    )


def vpath(x1, y1, y2, x2, **kw):
    """Long L-shaped route: vertically at x1, then horizontally to x2 at y2."""
    sign = 1 if x2 > x1 else -1
    return arrow(
        f"M {x1} {y1} V {y2 - R} Q {x1} {y2} {x1 + sign * R} {y2} H {x2}",
        **kw,
    )


def alabel(x, y, text, *, color=None, anchor="middle", gap=8):
    """Arrow label in a paper mask, sitting `gap` px above the connector at y."""
    w = -(-(5.6 * len(text) + 14) // 4) * 4  # round up to the 4px grid
    h = 12
    if anchor == "middle":
        rx = x - w / 2
    elif anchor == "start":
        rx = x
    else:
        rx = x - w
    top = y - gap - h
    LABELS.append((rx, top, rx + w, top + h))
    return (
        f'<rect x="{rx:.0f}" y="{top:.0f}" width="{w:.0f}" height="{h}" rx="2" fill="{PAPER}"/>'
        f'<text x="{rx + w / 2:.0f}" y="{top + 9:.0f}" fill="{color or SOFT}" font-size="8" '
        f'font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{esc(text)}</text>'
    )


def side_label(x, y, text, *, anchor="start", color=None):
    """Vertical-segment label placed beside the line.

    The mask starts 8px right of `x` so the connector stays visible with the
    6-10px gap SKILL.md §6 rule 2 requires.
    """
    w = -(-(5.6 * len(text) + 12) // 4) * 4  # round up to the 4px grid
    LABELS.append((x + 4, y - 9, x + 4 + w, y + 3))
    return (
        f'<rect x="{x + 4}" y="{y - 9}" width="{w:.0f}" height="12" rx="2" '
        f'fill="{PAPER}"/>'
        f'<text x="{x + 8}" y="{y}" fill="{color or SOFT}" font-size="8" font-family="{MONO}" '
        f'text-anchor="{anchor}" letter-spacing="0.06em">{esc(text)}</text>'
    )


def ring(x, y):
    """End glyph (type-state convention): ringed dot."""
    SHAPES.append(("ring", x, y, 8))
    return (
        f'<circle cx="{x}" cy="{y}" r="8" fill="none" stroke="{MUTED}" stroke-width="1.2"/>'
        f'<circle cx="{x}" cy="{y}" r="5" fill="{MUTED}"/>'
    )


def end_label(x, y, text):
    """Caption beside an end glyph."""
    return (
        f'<text x="{x + 16}" y="{y + 3}" fill="{MUTED}" font-size="9" '
        f'font-family="{MONO}">{esc(text)}</text>'
    )


def defs(prefix):
    return f'''<defs>
  <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/>
  </marker>
  <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/>
  </marker>
  <marker id="arrow-soft" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="{SOFT}"/>
  </marker>
</defs>'''


def svg_open(prefix, w, h, title, desc):
    return f'''<svg role="img" aria-labelledby="{prefix}-title {prefix}-desc"
     viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">
  <title id="{prefix}-title">{esc(title)}</title>
  <desc id="{prefix}-desc">{esc(desc)}</desc>
  {defs(prefix)}
  <rect width="100%" height="100%" fill="{PAPER}"/>'''


# --- Figure 1: the six-step pipeline (macro) -------------------------------

def figure_pipeline() -> str:
    s = [svg_open("flow-pipeline", 960, 900,
                  "DevFlow 六步流水线总览",
                  "从 project.yaml 到 delivery.json 的运行流程：六个固定顺序的步骤，"
                  "每步由适配器执行后封存工件，再由门禁模式决定该步终态是 Locked 还是 Done。")]
    mid = 480
    # nodes
    s.append(oval(mid, 16, 300, 48, ["harness run --project X"]))
    s.append(box(mid - 120, 104, 240, 56, ["Project Manager", "加载 + 校验 project.yaml"],
                 tag="PM"))
    s.append(box(mid - 120, 208, 240, 56, ["Workflow Controller", "run() 按 STEP_ORDER 循环"],
                 tag="WC", fill=ACCENT_TINT, stroke=ACCENT))
    s.append(box(mid - 120, 312, 240, 56, ["单步 launch_step", "适配器 → 封存 → .locked"],
                 tag="STEP"))
    s.append(diamond(mid, 456, 140, 64, ["门禁强制？", "由 size 决定"]))
    s.append(box(668, 428, 220, 56, ["Locked", "需签名 Acknowledgement"], tag="GATE"))
    s.append(box(mid - 120, 584, 240, 56, ["Done", "trivial/session 跳过门禁"], tag="FR-12"))
    s.append(box(mid - 120, 680, 240, 56, ["Run Event Log", "每步一条 · AD-14"], tag="LOG"))
    s.append(oval(mid, 784, 300, 48, ["delivery.json"]))
    # arrows
    s.append(straight(mid, 64, mid, 104))
    s.append(straight(mid, 160, mid, 208))
    s.append(straight(mid, 264, mid, 312))
    s.append(straight(mid, 368, mid, 392))
    s.append(straight(620, 456, 668, 456))
    s.append(straight(mid, 520, mid, 584))
    s.append(vpath(778, 484, 708, 600))          # Locked -> Run Event Log (from right)
    s.append(straight(mid, 640, mid, 680))
    s.append(straight(mid, 736, mid, 784))
    # loop back to the controller, on a clear left channel (x=88)
    s.append(arrow(f"M {mid - 120} 708 H 104 Q 88 708 88 692 V 244 Q 88 228 104 228 H {mid - 120}",
                   dash="5,4"))
    # labels
    s.append(alabel(644, 456, "是"))
    s.append(side_label(480, 556, "否"))
    s.append(side_label(88, 640, "下一步骤 · 顺序固定 (AD-15)"))
    s.append('</svg>')
    return "\n".join(s)


# --- Figure 2: one step's lifecycle ---------------------------------------

def figure_step_lifecycle() -> str:
    s = [svg_open("flow-step", 980, 1024,
                  "单个步骤的生命周期",
                  "launch_step 的判定顺序：先看跨调用幂等标记，再看前置步骤是否封存，"
                  "然后分派适配器、封存工件、写标记，最后由 step_status 解析终态。"
                  "三个判定各有自己的中止出口，标在右侧。")]
    mid = 480
    # nodes
    s.append(oval(mid, 16, 300, 48, ["launch_step(step)"]))
    s.append(diamond(mid, 148, 190, 60, ["跨调用幂等？", ".locked 已存在"]))
    s.append(diamond(mid, 320, 190, 60, ["前置步骤已封存？", "AD-15 前置"]))
    s.append(box(mid - 120, 448, 240, 56, ["适配器 dispatch", "ADAPTER_REGISTRY[mode]"],
                 tag="EXEC"))
    s.append(diamond(mid, 592, 190, 60, ["返回 succeeded？"]))
    s.append(box(mid - 130, 720, 260, 56, ["封存工件 + 写 .locked",
                                           "put_pending → lock → marker"], tag="AD-3"))
    s.append(box(mid - 130, 824, 260, 56, ["step_status 解析终态", "单一解析器"], tag="AD-24"))
    s.append(oval(mid, 928, 300, 48, ["StepStatus"]))
    # end glyphs — one per abort path, so no arrow dead-ends in space
    for y in (148, 320, 592):
        s.append(straight(mid + 190, y, 712, y))
        s.append(ring(720, y))
    s.append(end_label(736, 148, "返回已有状态（不重跑适配器）"))
    s.append(end_label(736, 320, "抛 StepUnreachable（拒绝执行）"))
    s.append(end_label(736, 592, "抛 ExecutorInvocationFailed"))
    # spine
    s.append(straight(mid, 64, mid, 88))
    s.append(straight(mid, 208, mid, 260))
    s.append(straight(mid, 380, mid, 448))
    s.append(straight(mid, 504, mid, 532))
    s.append(straight(mid, 652, mid, 720))
    s.append(straight(mid, 776, mid, 824))
    s.append(straight(mid, 880, mid, 928))
    # branch labels
    s.append(alabel(678, 148, "是", gap=6))
    s.append(side_label(480, 234, "否"))
    s.append(alabel(678, 320, "否", gap=6))
    s.append(side_label(480, 414, "是"))
    s.append(alabel(678, 592, "否", gap=6))
    s.append(side_label(480, 686, "是"))
    s.append('</svg>')
    return "\n".join(s)


# --- Figure 3: step terminal states ---------------------------------------

def figure_states() -> str:
    s = [svg_open("flow-states", 960, 380,
                  "步骤终态及其转移",
                  "四态：Pending 在拿到签名裁决后转为 Locked 或 Failed；"
                  "trivial/session 档直接跳过门禁进入 Done。Done 与 Locked 是不同的终态。")]
    s.append(f'<circle cx="80" cy="200" r="6" fill="{INK}"/>')
    s.append(box(140, 172, 180, 56, ["Pending", "门禁强制 · 无裁决"], tag="AD-24"))
    s.append(box(440, 96, 200, 56, ["Locked", "accepted"], tag="GATE",
                 fill=ACCENT_TINT, stroke=ACCENT))
    s.append(box(440, 252, 200, 56, ["Failed", "rejected"], tag="GATE"))
    s.append(box(440, 16, 200, 56, ["Done", "跳过门禁"], tag="FR-12", dash="4,3",
                 fill=PAPER2, stroke=MUTED))
    s.append(ring(700, 124))
    s.append(ring(700, 280))
    # transitions
    s.append(straight(86, 200, 140, 200))
    s.append(arrow(f"M 80 194 V 52 Q 80 44 88 44 H 440", dash="5,4"))
    s.append(arrow(f"M 320 186 H 432 Q 440 186 440 178 V 124"))
    s.append(arrow(f"M 320 214 H 432 Q 440 214 440 222 V 252"))
    s.append(straight(640, 124, 692, 124))
    s.append(straight(640, 280, 692, 280))
    # labels
    s.append(side_label(80, 108, "size=trivial|session"))
    s.append(alabel(392, 178, "accepted", gap=6))
    s.append(alabel(392, 222, "rejected", gap=6))
    s.append('</svg>')
    return "\n".join(s)


# --- Figure 4: failure path + retry ladder --------------------------------

def figure_failure() -> str:
    s = [svg_open("flow-failure", 960, 520,
                  "失败路径与重试阶梯",
                  "步骤失败先append 一条只增不改的 Error Store 记录，然后逐级升档："
                  "rung 1 同执行者重试，rung 2 换 LLM，rung 3 换 agent，rung 4 用已晋级 skill，"
                  "rung 5 交回人工并暂停。")]
    s.append(box(40, 200, 180, 56, ["步骤失败", "adapter 返回 failed"], tag="FAIL"))
    s.append(box(272, 200, 200, 56, ["Error Store append", "只增不改 · AD-4"], tag="AD-4"))
    rungs = [
        (40, ["rung 1 · 同 agent 同 LLM", "重试同一执行者"]),
        (120, ["rung 2 · 同 agent 换 LLM", "换一个模型再试"]),
        (200, ["rung 3 · 换 agent + 更强 LLM", "查 bench 推荐"]),
        (280, ["rung 4 · 用 promoted skill", "AD-6 skill 晋级"]),
    ]
    for y, lines in rungs:
        s.append(box(560, y, 320, 56, lines))
    s.append(box(560, 392, 320, 56, ["rung 5 · 人工介入", "暂停 · 不再自动"], tag="HITL",
                 dash="4,3", fill=PAPER2, stroke=MUTED))
    # arrows
    s.append(straight(220, 228, 272, 228))                       # fail -> error store
    s.append(arrow(f"M 130 200 V 76 Q 130 68 138 68 H 560"))     # fail -> rung 1 (above)
    s.append(straight(720, 96, 720, 120))                        # rung1 -> rung2
    s.append(straight(720, 176, 720, 200))                       # rung2 -> rung3
    s.append(straight(720, 256, 720, 280))                       # rung3 -> rung4
    s.append(straight(720, 336, 720, 392))                       # rung4 -> rung5
    # labels
    s.append(side_label(736, 108, "仍失败", ))
    s.append(side_label(736, 188, "仍失败"))
    s.append(side_label(736, 268, "仍失败"))
    s.append(side_label(736, 364, "仍失败"))
    s.append('</svg>')
    return "\n".join(s)


# --- Page assembly ---------------------------------------------------------

BUILT: dict[str, str] = {}

CARDS = [
    ("WHY", "三条决定了整个形态的规则", [
        "AD-15 六步顺序写死在代码里，改 YAML 顺序会在启动时抛错",
        "AD-11 Done 与 Locked 是两个不同的终态：跳过门禁 ≠ 通过门禁",
        "AD-24 步骤终态只有一个解析器 step_status，谁都不许自己算",
    ]),
    ("WHERE", "数据落在哪", [
        "var/projects/&lt;id&gt;/project.yaml — 项目定义",
        "var/projects/&lt;id&gt;/runs/&lt;run&gt;/&lt;step&gt;/.locked — 封存标记",
        "var/harness.sqlite — 工件 / 错误 / 回归集 / 成本",
        "var/devflow.sqlite — 运行事件 / 编辑锁",
    ]),
    ("HOW", "怎么看它跑起来", [
        "uv run harness run -p tests/fixtures/sample-projects/python-hello",
        "uv run harness serve   → 127.0.0.1:8137",
        "human 模式需要 stdin：yes x | uv run harness run ...",
    ]),
]


def card(eyebrow, title, items, dot):
    lis = "".join(f"<li>{i}</li>" for i in items)
    return f'''<div class="card">
      <p class="eyebrow">{eyebrow}</p>
      <div class="card-header"><span class="card-dot {dot}"></span><h3>{title}</h3></div>
      <ul>{lis}</ul>
    </div>'''


def page() -> tuple[str, list[str]]:
    problems: list[str] = []
    for key, fn in (("pipeline", figure_pipeline), ("step", figure_step_lifecycle),
                    ("states", figure_states), ("failure", figure_failure)):
        BUILT[key], found = build(fn)
        problems.extend(f"{key}: {p}" for p in found)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DevFlow 运行流程</title>
<style>
  :root {{
    --paper: {PAPER}; --paper-2: {PAPER2}; --ink: {INK}; --muted: {MUTED};
    --soft: {SOFT}; --accent: {ACCENT}; --rule: {RULE};
    --serif: {SERIF}; --mono: {MONO};
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--paper); color: var(--ink);
         font-family: var(--mono); line-height: 1.6; }}
  .wrap {{ max-width: 1040px; margin: 0 auto; padding: 56px 32px 72px; }}
  header {{ margin-bottom: 44px; }}
  .eyebrow, .kicker {{ font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
                       color: var(--soft); margin: 0 0 10px; }}
  h1 {{ font-family: var(--serif); font-weight: 400; font-size: 30px; margin: 0 0 12px;
        letter-spacing: -0.01em; }}
  .sub {{ color: var(--muted); font-size: 13px; margin: 0; max-width: 62ch; }}
  figure {{ margin: 0 0 56px; }}
  figcaption {{ margin-top: 14px; color: var(--muted); font-size: 11.5px; }}
  figcaption b {{ color: var(--ink); font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: 1.15fr 1fr 0.9fr; gap: 20px;
           margin: 56px 0 0; }}
  @media (max-width: 860px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{ background: #fff; border: 1px solid var(--rule); border-radius: 6px;
           padding: 20px; }}
  .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
  .card h3 {{ font-family: var(--serif); font-weight: 400; font-size: 16px; margin: 0; }}
  .card-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
  .coral {{ background: var(--accent); }}
  .blue {{ background: {LINK}; }}
  .ink {{ background: var(--ink); }}
  .card ul {{ margin: 0; padding-left: 16px; font-size: 11.5px; color: var(--muted); }}
  .card li {{ margin-bottom: 6px; }}
  footer {{ margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--rule);
            color: var(--soft); font-size: 10.5px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="kicker">DEVFLOW HARNESS · software-v1</p>
    <h1>运行流程</h1>
    <p class="sub">流程固定、执行者可换：六个步骤的顺序由代码写死（AD-15），
       每一步背后的 agent / LLM / skills 可以随时替换并基准测试。
       下面四张图分别是宏观流水线、单步内部判定、步骤终态与失败路径。</p>
  </header>

  <figure>
    {BUILT['pipeline']}
    <figcaption><b>六步流水线。</b> project.yaml 经 Project Manager 校验后交给
      Workflow Controller；每个步骤由适配器执行、把结果封存成工件并写一个
      <span style="font-family:var(--mono)">.locked</span> 标记，该标记同时是下一步骤的前置条件。
      size 决定门禁是否强制：epic/project 需要签名裁决（Locked），
      trivial/session 直接跳过（Done）。</figcaption>
  </figure>

  <figure>
    {BUILT['step']}
    <figcaption><b>单个步骤的判定顺序。</b> 三道判定都在动适配器之前完成：
      跨调用幂等（标记已存在就直接复用，不重跑）、前置步骤必须已封存（AD-15）、
      适配器必须返回 succeeded。注意<span style="color:var(--accent)">前置条件是「工件已封存」，
      不是「已裁决」</span>——两者是不同的问题。</figcaption>
  </figure>

  <figure>
    {BUILT['states']}
    <figcaption><b>四个终态。</b> Pending 在拿到签名裁决后转为 Locked（accepted）或
      Failed（rejected）；trivial/session 档不经过门禁，直接是 Done。
      <b>Done ≠ Locked</b>：前者表示门禁被跳过，后者表示门禁通过了（AD-11）。</figcaption>
  </figure>

  <figure>
    {BUILT['failure']}
    <figcaption><b>失败与重试阶梯。</b> 失败先记一条只增不改的 Error Store 记录（AD-4），
      再逐级升档：同执行者重试 → 换 LLM → 换 agent → 用已晋级的 skill；
      第五档交回人工并暂停，不再自动推进。</figcaption>
  </figure>

  <div class="grid">
    {card(*CARDS[0], dot="coral")}
    {card(*CARDS[1], dot="blue")}
    {card(*CARDS[2], dot="ink")}
  </div>

  <footer>
    由 tools/make_flow_diagram.py 生成 · 皮肤取自 pi.dev 品牌色（evening-blue / warm-white /
    terracotta）· 图中技术标识符为源码中的真实命名，中文标签为说明 ·
    正文字体使用品牌 mono 栈并回退到系统中文字体。
  </footer>
</div>
</body>
</html>''', problems





# --- Geometry verification -------------------------------------------------


def _endpoint(d: str) -> tuple[float, float]:
    """Final coordinate of a path `d` built from M/L/H/V/Q commands."""
    import re as _re

    x = y = 0.0
    tokens = _re.findall(r"([MLHVQ])([^MLHVQ]*)", d)
    for cmd, args in tokens:
        nums = [float(n) for n in _re.findall(r"-?\d+\.?\d*", args)]
        if cmd == "M" or cmd == "L":
            x, y = nums[0], nums[1]
        elif cmd == "H":
            x = nums[0]
        elif cmd == "V":
            y = nums[0]
        elif cmd == "Q":
            x, y = nums[2], nums[3]
    return x, y


def _on_a_shape(px: float, py: float) -> bool:
    """True when (px,py) resolves on a shape's boundary (markers sit on edges)."""
    tol = 2
    for shape in SHAPES:
        kind = shape[0]
        if kind == "rect":
            _, x0, y0, x1, y1 = shape
            if x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol:
                return True
        elif kind == "diamond":
            _, cx, cy, hw, hh = shape
            # Normalised diamond distance: 1.0 is the edge.
            d = abs(px - cx) / hw + abs(py - cy) / hh
            if d <= 1 + tol / min(hw, hh):
                return True
        elif kind == "ring":
            _, cx, cy, r = shape
            if (px - cx) ** 2 + (py - cy) ** 2 <= (r + tol) ** 2:
                return True
    return False


def _overlaps(rect: tuple, shape: tuple) -> bool:
    """True when a label `rect` genuinely overlaps `shape` (real geometry)."""
    lx0, ly0, lx1, ly1 = rect
    kind = shape[0]
    if kind == "rect":
        _, x0, y0, x1, y1 = shape
        return lx0 < x1 - 1 and lx1 > x0 + 1 and ly0 < y1 - 1 and ly1 > y0 + 1
    if kind == "diamond":
        _, cx, cy, hw, hh = shape
        # Sample the label rect: any sample inside the diamond is an overlap.
        pts = [(lx0, ly0), (lx1, ly0), (lx0, ly1), (lx1, ly1),
               ((lx0 + lx1) / 2, ly0), ((lx0 + lx1) / 2, ly1),
               (lx0, (ly0 + ly1) / 2), (lx1, (ly0 + ly1) / 2)]
        return any(abs(px - cx) / hw + abs(py - cy) / hh < 1 for px, py in pts)
    if kind == "ring":
        _, cx, cy, r = shape
        nearest_x = min(max(cx, lx0), lx1)
        nearest_y = min(max(cy, ly0), ly1)
        return (nearest_x - cx) ** 2 + (nearest_y - cy) ** 2 < (r - 1) ** 2
    return False


def build(figure_fn) -> tuple[str, list[str]]:
    """Run one figure builder and verify it against its own shapes.

    The four SVGs are independent coordinate spaces; verifying them in one
    accumulator let a box in figure 4 "rescue" a dangling connector in figure 2,
    which is how the first dangling arrow went unnoticed by the checker.
    """
    SHAPES.clear(); ARROWS.clear(); LABELS.clear()
    svg = figure_fn()
    return svg, verify()


def verify() -> list[str]:
    """Return the geometry problems in the figure just built.

    Catches the failure the first render shipped: connectors terminating in
    empty space, because the node they were meant to reach sat somewhere else.
    """
    problems = []
    for px, py in ARROWS:
        if not _on_a_shape(px, py):
            problems.append(f"connector ends at ({px:.0f},{py:.0f}) on no shape")
    for rect in LABELS:
        for shape in SHAPES:
            # A label mask overlapping a node clips its text on the border
            # (SKILL.md §6 rule 6).
            if _overlaps(rect, shape):
                problems.append(
                    f"label mask ({rect[0]:.0f},{rect[1]:.0f})-({rect[2]:.0f},{rect[3]:.0f}) "
                    f"overlaps {shape[0]} {shape[1:]}"
                )
    return problems


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "docs" / "devflow-flow.html"
    html, problems = page()
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"shapes={len(SHAPES)} connectors={len(ARROWS)} labels={len(LABELS)}")
    for problem in problems:
        print(f"  GEOMETRY: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
