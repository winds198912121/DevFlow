#!/usr/bin/env python3
"""Export the DevFlow flow diagrams to standalone .svg + .png files.

Manual only, per the diagram-design export procedure: generating the page never
emits images. Run it when you actually want files to share:

    uv run python tools/export_flow_diagrams.py            # 2x PNG
    uv run python tools/export_flow_diagrams.py --scale 3  # print/retina

Writes `docs/img/devflow-flow-<slug>.svg` and `.png`, one pair per figure.

Two deliberate departures from the skill's default procedure, both because this
source is a multi-figure document rather than a single-diagram file:

  * All four `<svg>` blocks are exported, not just the first. The skill tells you
    to refuse and ask on a multi-SVG *gallery*; this is not a gallery — it is one
    page whose four figures are meant to travel as four images, so refusing would
    be unhelpful. Slugs come from each figure's own `aria-labelledby` prefix.
  * No Google Fonts `@import` is injected. The skin is pi.dev's brand palette,
    whose families (Plantin MT Pro, Commit Mono) are self-hosted on pi.dev and
    absent from Google Fonts — the style guide forbids linking a non-Google-Fonts
    URL. The stacks already fall back to system serif/mono and system CJK, which
    is exactly what the browser render uses too.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "devflow-flow.html"
OUT_DIR = ROOT / "docs" / "img"

SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL)
# The value holds both ids (`flow-pipeline-title flow-pipeline-desc`), so the
# match must not be anchored to the closing quote.
LABEL_RE = re.compile(r'aria-labelledby="([a-z0-9-]+)-title')


def standalone(raw: str) -> str:
    """Make one `<svg>` block a well-formed, self-contained document."""
    # A standalone .svg is parsed as strict XML, so the namespace must be explicit.
    if 'xmlns="http://www.w3.org/2000/svg"' not in raw:
        raw = raw.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    if "viewBox=" not in raw:
        raise SystemExit("no viewBox on an <svg> block; refusing to guess a size")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", type=int, default=2,
                        help="Raster scale for the PNG (default 2; 3 for print).")
    parser.add_argument("--source", default=str(SOURCE))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"{source} not found; run tools/make_flow_diagram.py first")

    if shutil.which("rsvg-convert") is None:
        raise SystemExit(
            "rsvg-convert (librsvg) not found — install it (brew install librsvg) "
            "and re-run. Not installing it for you."
        )

    html = source.read_text(encoding="utf-8")
    blocks = SVG_RE.findall(html)
    if not blocks:
        raise SystemExit(f"no <svg> block in {source}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for raw in blocks:
        labelled = LABEL_RE.search(raw)
        if not labelled:
            raise SystemExit("an <svg> block has no prefixed aria-labelledby")
        slug = labelled.group(1).replace("flow-", "", 1)
        svg_path = OUT_DIR / f"devflow-flow-{slug}.svg"
        png_path = OUT_DIR / f"devflow-flow-{slug}.png"
        svg_path.write_text(standalone(raw), encoding="utf-8")
        subprocess.run(
            ["rsvg-convert", "-z", str(args.scale), "-o", str(png_path), str(svg_path)],
            check=True,
        )
        size = png_path.stat().st_size
        print(f"{slug:9} -> {png_path.relative_to(ROOT)}  ({size // 1024} KB)")

    print(f"\n{len(blocks)} diagram(s) exported to {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
