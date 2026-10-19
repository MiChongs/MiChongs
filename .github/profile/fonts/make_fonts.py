#!/usr/bin/env python3
"""
Rebuild the font subsets used by build.py.

The SVG panels draw text as glyph outlines, so only the glyphs that can ever
appear are kept: a generous Latin and symbols range, since every string,
static or from the API, is Latin.

Sources (all SIL OFL 1.1):
  Geist           https://www.npmjs.com/package/geist  (dist/fonts/geist-sans)
  JetBrains Mono  https://github.com/JetBrains/JetBrainsMono

Usage:
  python make_fonts.py [--geist DIR] [--jbm DIR]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).resolve().parent

LATIN = (
    list(range(0x20, 0x7F))
    + list(range(0xA0, 0x180))
    + list(range(0x2010, 0x2060))  # dashes, quotes, bullets, ellipsis
    + list(range(0x2190, 0x2200))  # arrows
    + list(range(0x2500, 0x2600))  # box drawing, blocks, geometric shapes
    + [0x276F, 0x2713, 0x2715]
)


def write_subset(font: TTFont, codepoints: list[int], out: Path) -> None:
    opts = subset.Options()
    opts.layout_features = ["kern", "liga", "calt"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.hinting = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=codepoints)
    sub.subset(font)
    font.save(out)
    print(f"{out.name:28s} {out.stat().st_size / 1024:7.1f} KiB")


def static(path: Path, wght: int | None = None) -> TTFont:
    font = TTFont(path)
    if wght is not None and "fvar" in font:
        font = instancer.instantiateVariableFont(font, {"wght": wght})
    return font


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geist", type=Path)
    ap.add_argument("--jbm", type=Path)
    args = ap.parse_args()

    if args.geist:
        for weight in ("Regular", "Medium", "SemiBold"):
            write_subset(static(args.geist / f"Geist-{weight}.ttf"), LATIN, HERE / f"Geist-{weight}.ttf")
    if args.jbm:
        for weight in ("Regular", "Bold"):
            write_subset(static(args.jbm / f"JetBrainsMono-{weight}.ttf"), LATIN, HERE / f"JetBrainsMono-{weight}.ttf")


if __name__ == "__main__":
    main()
