#!/usr/bin/env python3
"""
Build the SVG panels of the MiChongs profile README.

Design: "川 · Flow" — 川 means river; three streams stand for Go, Rust and
Kotlin, and the river runs through every panel. Every panel is rendered twice
(dark / light) into assets/ and picked by <picture> in README.md.

Text is converted into glyph outlines (Geist, JetBrains Mono, Noto SC), so the
panels look identical on every device and need no web fonts. Stars, followers
and contributions come from the GitHub GraphQL API; the featured projects
block in README.md is rewritten in star order.

Run locally:   pip install -r .github/profile/requirements.txt
               GITHUB_TOKEN=$(gh auth token) python .github/profile/build.py
Run in CI:     handled by .github/workflows/profile.yml
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "assets"
RAW = "https://raw.githubusercontent.com/MiChongs/MiChongs/main"

# ----------------------------------------------------------------------
# Content  (edit here; Chinese text needs `fonts/make_fonts.py` re-run)
# ----------------------------------------------------------------------
USER = "MiChongs"
SINCE = 2019

TYPING = [
    "building proxy cores in Rust",
    "shipping gateways & platforms in Go",
    "crafting Android tooling in Kotlin",
    "learning in public since 2019",
]

WHOAMI = [
    ("Role", "Backend & Systems Developer"),
    ("Languages", "Go · Rust · Kotlin · TypeScript"),
    ("Focus", "Proxy cores · Gateways · PAM · Platforms"),
    ("Stack", "Gin · gRPC · Temporal · NATS · PostgreSQL"),
    ("Desktop", "Kubuntu · KDE Plasma on Wayland"),
    ("Editors", "Zed · VS Code · Android Studio"),
    ("AI pair", "Claude Code · Codex"),
    ("Uptime", "{uptime}"),
    None,
    ("GitHub", "{repos} original repos · {stars} stars · {followers} followers"),
    ("Activity", "{contribs} contributions in the past year"),
    ("Motto", "始于热爱，忠于长期主义"),
]

# Whitelist for "Featured work": the top MAX_FEATURED by stars are shown.
MAX_FEATURED = 8
PROJECTS: list[dict[str, Any]] = [
    {"repo": "WutherCore", "tags": ["rust", "tun", "proxy"],
     "desc": "Modular cross-platform proxy core — TUN/TPROXY capture, policy routing, DNS, subscriptions and a management API."},
    {"repo": "Wayfort", "tags": ["go", "next.js", "bastion"],
     "desc": "Browser-native privileged access management — SSH, RDP, VNC, databases and file transfer with zero client."},
    {"repo": "user_system", "tags": ["node.js", "mysql", "auth"],
     "desc": "User authentication & management system — the project that took me from apps into backend engineering."},
    {"repo": "aegis", "tags": ["go", "temporal", "nats"],
     "desc": "High-performance multi-tenant user platform with workflow orchestration on Gin, PostgreSQL, Redis and Temporal."},
    {"repo": "Frida-RS", "tags": ["kernelsu", "frida", "webui"],
     "desc": "Frida Server for KernelSU — a Rust supervisor with a Material\u00a03 WebUI, packaged for four ABIs."},
    {"repo": "ChuanyiHooker", "tags": ["xposed", "android", "kavaref"],
     "desc": "Xposed module host — one hooker per target app, discovered at runtime and scoped automatically."},
    {"repo": "Proxy-RS", "tags": ["sing-box", "ratatui", "cli"],
     "desc": "Cross-platform sing-box & mihomo manager with native services, a Ratatui TUI, tray, telemetry and CLI."},
    {"repo": "Leaf-IDE", "tags": ["android", "ide"],
     "desc": "A modern IDE for Android written in Kotlin, supporting web projects, native projects and more."},
    {"repo": "singbox-board", "tags": ["ratatui", "daemon", "tui"],
     "desc": "Root daemon & terminal dashboard for sing-box — core versions, configs, subscriptions and containers."},
    {"repo": "cronet-rs", "tags": ["cronet", "http3", "ffi"],
     "desc": "Rust bindings for Chromium Cronet with NaiveProxy-ready H2/H3 bidirectional streams."},
    {"repo": "Readme", "tags": ["next.js", "prisma", "cms"],
     "desc": "Personal homepage generator & blog CMS built with Next.js, React, Prisma and Tailwind CSS."},
]

# (label, icon); icon = skill-icons file stem, "si:<slug>:<hex>" or "txt:<label>:<hex>"
STACK = [
    ("Languages", [("Go", "GoLang"), ("Rust", "Rust"), ("Kotlin", "Kotlin-{T}"),
                   ("TypeScript", "TypeScript"), ("Java", "Java-{T}"), ("Python", "Python-{T}"),
                   ("Bash", "Bash-{T}")]),
    ("Backend & Data", [("Gin", "si:gin:008ECF"), ("gRPC", "txt:gRPC:2DA6B0"),
                        ("Temporal", "si:temporal:{fg}"), ("NATS", "si:natsdotio:27AAE1"),
                        ("PostgreSQL", "PostgreSQL-{T}"), ("Redis", "Redis-{T}"), ("MySQL", "MySQL-{T}")]),
    ("Systems · Mobile · Web", [("Tokio", "si:tokio:{fg}"), ("Ratatui", "si:ratatui:{fg}"),
                                ("Android", "AndroidStudio-{T}"), ("Compose", "si:jetpackcompose:4285F4"),
                                ("Next.js", "NextJS-{T}"), ("React", "React-{T}"),
                                ("Tailwind", "TailwindCSS-{T}")]),
    ("Infra & Tooling", [("Linux", "Linux-{T}"), ("Docker", "Docker"), ("Nginx", "Nginx"),
                         ("Actions", "GithubActions-{T}"), ("Cloudflare", "Cloudflare-{T}"),
                         ("Gradle", "Gradle-{T}"), ("Git", "Git")]),
]

RIVER = [
    ("2019", "First line of code", "写下第一行代码", "syntax · algorithms · debugging"),
    ("2021", "Learning in public", "加入 GitHub，走进开源", "open source · releases · docs"),
    ("2022–23", "Android & Kotlin", "专注 Android 与 Kotlin", "Leaf-IDE · UI architecture"),
    ("2024–25", "Apps → services", "从客户端走向后端", "user_system · auth · APIs"),
    ("2026 →", "Systems & infra", "系统、平台与基础设施", "WutherCore · Wayfort · aegis"),
]

SECTIONS = [
    ("whoami", "Who am I", "关于我", "~/whoami"),
    ("work", "Featured work", "精选项目", "sorted by stars · auto-updated"),
    ("stack", "Toolbox", "技术栈", "~/stack"),
    ("river", "The river so far", "来路", "since 2019"),
    ("activity", "Contributions", "贡献", "3D calendar · daily"),
]

ASCII_CHUAN = [
    "    -@%%#+.            .@@%%#-",
    "    -@@@@=    @@%%#-   .@@@@# ",
    "    -@@@@=    @@@@#    .@@@@# ",
    "    -@@@@=    @@@@#    .@@@@# ",
    "    -@@@@=    @@@@#    .@@@@# ",
    "    -@@@@=    @@@@#    .@@@@# ",
    "    -@@@@-    @@@@#    .@@@@# ",
    "    =@@@@:    @@@@#    .@@@@# ",
    "    +@@@@.    @@@@#    .@@@@# ",
    "    #@@@%     @@@@#    .@@@@# ",
    "    @@@@-     @@@@#    .@@@@# ",
    "   :@@@#      @@@@#    .@@@@# ",
    "   #@@%       @@@@#    .@@@@# ",
    "  =@@*        @@%*-    .@@@@# ",
    " :@%-                  .@@@@# ",
    "-*:                    .@%#+: ",
]

# ----------------------------------------------------------------------
# Design tokens
# ----------------------------------------------------------------------
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "panel": "#0f141b", "panel2": "#0b0f14", "border": "#222b36", "grid": "#273140",
        "text": "#e6edf3", "sub": "#9ba8b8", "muted": "#647184", "faint": "#1a212b",
        "chip": "#161d26", "fg": "#ffffff", "tile": "#242938",
        "a1": "#5eead4", "a2": "#38bdf8", "a3": "#a78bfa", "warm": "#fbbf24", "ok": "#4ade80",
        "glow": "0.20",
    },
    "light": {
        "panel": "#ffffff", "panel2": "#f6f8fa", "border": "#e2e7ee", "grid": "#d9e0e8",
        "text": "#0f172a", "sub": "#475569", "muted": "#8a96a8", "faint": "#eef2f6",
        "chip": "#f1f4f8", "fg": "#000000", "tile": "#F4F2ED",
        "a1": "#0d9488", "a2": "#0284c7", "a3": "#7c3aed", "warm": "#d97706", "ok": "#16a34a",
        "glow": "0.12",
    },
}
PALETTE = ["#f87171", "#fb923c", "#fbbf24", "#4ade80", "#2dd4bf", "#38bdf8", "#818cf8", "#e879f9"]
W = 880  # every full-width panel shares this viewBox width


# ----------------------------------------------------------------------
# Fonts → glyph outlines
# ----------------------------------------------------------------------
class Font:
    def __init__(self, key: str, file: str) -> None:
        path = HERE / "fonts" / file
        self.key = key
        self.tt = TTFont(path)
        self.upm = self.tt["head"].unitsPerEm
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        self._paths: dict[int, str] = {}

    def shape(self, text: str) -> list[tuple[int, int, int]]:
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": False, "calt": False})
        out = []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            if info.codepoint == 0:
                ch = text[info.cluster]
                raise SystemExit(f"glyph for {ch!r} missing in {self.key}; re-run fonts/make_fonts.py")
            out.append((info.codepoint, pos.x_advance, pos.x_offset))
        return out

    def path(self, gid: int) -> str:
        if gid not in self._paths:
            pen = SVGPathPen(self.glyphs, ntos=lambda v: f"{v:.0f}")
            self.glyphs[self.order[gid]].draw(pen)
            self._paths[gid] = pen.getCommands()
        return self._paths[gid]


FONTS = {
    "sans": Font("s", "Geist-Regular.ttf"),
    "sans-m": Font("m", "Geist-Medium.ttf"),
    "sans-sb": Font("b", "Geist-SemiBold.ttf"),
    "mono": Font("j", "JetBrainsMono-Regular.ttf"),
    "mono-b": Font("k", "JetBrainsMono-Bold.ttf"),
    "zh": Font("z", "NotoSansSC-Regular.ttf"),
    "serif": Font("h", "NotoSerifSC-Black.ttf"),
}


def width(s: str, font: str, size: float, ls: float = 0) -> float:
    f = FONTS[font]
    return sum(a for _, a, _ in f.shape(s)) * size / f.upm + ls * max(len(s) - 1, 0)


def wrap(s: str, font: str, size: float, max_w: float, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for word in s.split(" "):
        trial = f"{cur} {word}".strip()
        if width(trial, font, size) <= max_w:
            cur = trial
            continue
        lines.append(cur)
        cur = word
    lines.append(cur)
    if len(lines) > max_lines:
        last = lines[max_lines - 1]
        while width(last + "…", font, size) > max_w:
            last = last.rsplit(" ", 1)[0]
        lines = lines[: max_lines - 1] + [last.rstrip(",;—-") + "…"]
    return lines


# ----------------------------------------------------------------------
# SVG document
# ----------------------------------------------------------------------
@dataclass
class SVG:
    w: float
    h: float
    t: dict[str, str]
    title: str
    defs: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    css: list[str] = field(default_factory=list)
    glyphs: dict[str, str] = field(default_factory=dict)
    _ids: int = 0

    def uid(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}{self._ids}"

    def add(self, *parts: str) -> None:
        self.body.extend(parts)

    def glyph_run(self, x: float, y: float, s: str, font: str, size: float,
                  anchor: str = "start", ls: float = 0) -> tuple[str, float]:
        f = FONTS[font]
        k = size / f.upm
        run = f.shape(s)
        w = sum(a for _, a, _ in run) * k + ls * max(len(run) - 1, 0)
        x0 = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        uses, pen = [], 0.0
        for gid, adv, xo in run:
            d = f.path(gid)
            if d:
                gname = f"{f.key}{gid}"
                self.glyphs.setdefault(gname, d)
                uses.append(f'<use xlink:href="#{gname}" x="{pen + xo:.0f}"/>')
            pen += adv + ls / k
        g = f'<g transform="translate({x0:.2f} {y:.2f}) scale({k:.5f} {-k:.5f})">{"".join(uses)}</g>'
        return g, w

    def text(self, x: float, y: float, s: str, font: str, size: float, fill: str,
             anchor: str = "start", ls: float = 0, attrs: str = "") -> float:
        g, w = self.glyph_run(x, y, s, font, size, anchor, ls)
        self.add(f'<g fill="{fill}"{attrs}>{g}</g>')
        return w

    def gradient_text(self, x: float, y: float, s: str, font: str, size: float, grad: str,
                      anchor: str = "start", ls: float = 0) -> float:
        g, w = self.glyph_run(x, y, s, font, size, anchor, ls)
        mid = self.uid("m")
        x0 = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        self.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" '
                         f'width="{self.w}" height="{self.h}"><g fill="#fff">{g}</g></mask>')
        self.add(f'<rect x="{x0 - 2:.1f}" y="{y - size * 1.1:.1f}" width="{w + 4:.1f}" '
                 f'height="{size * 1.5:.1f}" fill="url(#{grad})" mask="url(#{mid})"/>')
        return w

    def linear(self, gid: str, stops: list[tuple[float, str, float]],
               x1: float = 0, y1: float = 0, x2: float = 1, y2: float = 0, user: bool = False) -> None:
        units = ' gradientUnits="userSpaceOnUse"' if user else ""
        s = "".join(f'<stop offset="{o}" stop-color="{c}" stop-opacity="{a}"/>' for o, c, a in stops)
        self.defs.append(f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{units}>{s}</linearGradient>')

    def radial(self, gid: str, color: str, opacity: float | str) -> None:
        self.defs.append(f'<radialGradient id="{gid}"><stop offset="0" stop-color="{color}" '
                         f'stop-opacity="{opacity}"/><stop offset="1" stop-color="{color}" stop-opacity="0"/>'
                         f'</radialGradient>')

    def panel(self, x: float = 0, y: float = 0, w: float | None = None, h: float | None = None,
              r: float = 16) -> None:
        w = self.w if w is None else w
        h = self.h if h is None else h
        gid = self.uid("p")
        self.linear(gid, [(0, self.t["panel"], 1), (1, self.t["panel2"], 1)], 0, 0, 0.6, 1)
        self.add(f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="{r}" '
                 f'fill="url(#{gid})" stroke="{self.t["border"]}"/>')

    def render(self) -> str:
        glyph_defs = "".join(f'<path id="{k}" d="{v}"/>' for k, v in self.glyphs.items())
        css = "".join(self.css)
        motion = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" fill="none" '
            f'role="img" aria-label="{html.escape(self.title)}">'
            f"<title>{html.escape(self.title)}</title>"
            f"<style>{css}{motion}</style>"
            f"<defs>{glyph_defs}{''.join(self.defs)}</defs>"
            f"{''.join(self.body)}</svg>\n"
        )


def save(name: str, svg: SVG) -> None:
    path = OUT / name
    data = svg.render()
    if not path.exists() or path.read_text(encoding="utf-8") != data:
        path.write_text(data, encoding="utf-8")
        print(f"  wrote {name} ({len(data) / 1024:.1f} KiB)")


# ----------------------------------------------------------------------
# Shared decorations
# ----------------------------------------------------------------------
def dot_grid(svg: SVG, cx: float, cy: float, rx: float, ry: float, gap: float = 22) -> None:
    pid, mid, gid = svg.uid("dg"), svg.uid("dm"), svg.uid("dr")
    svg.defs.append(f'<pattern id="{pid}" width="{gap}" height="{gap}" patternUnits="userSpaceOnUse">'
                    f'<circle cx="{gap / 2}" cy="{gap / 2}" r="1" fill="{svg.t["grid"]}"/></pattern>')
    svg.defs.append(f'<radialGradient id="{gid}"><stop offset="0" stop-color="#fff"/>'
                    f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>')
    svg.defs.append(f'<mask id="{mid}"><ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="url(#{gid})"/></mask>')
    svg.add(f'<rect width="{svg.w}" height="{svg.h}" fill="url(#{pid})" mask="url(#{mid})"/>')


def glow(svg: SVG, cx: float, cy: float, r: float, color: str, scale: float = 1.0) -> None:
    gid = svg.uid("gl")
    svg.radial(gid, color, f"{float(svg.t['glow']) * scale:.3f}")
    svg.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{gid})"/>')


def clip_panel(svg: SVG, r: float = 16) -> str:
    cid = svg.uid("c")
    svg.defs.append(f'<clipPath id="{cid}"><rect x="1" y="1" width="{svg.w - 2}" height="{svg.h - 2}" rx="{r}"/></clipPath>')
    return cid


def ping(r0: float, r1: float, dur: float = 2.4) -> str:
    return (f'<animate attributeName="r" values="{r0};{r1}" dur="{dur}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0.8;0" dur="{dur}s" repeatCount="indefinite"/>')


def octicon(name: str) -> str:
    raw = (HERE / "icons" / "octicons" / f"{name}.svg").read_text(encoding="utf-8")
    return re.search(r'<path d="([^"]+)"', raw).group(1)


def catmull_rom(points: list[tuple[float, float]]) -> str:
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


# ----------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------
def hero(t: dict[str, str]) -> SVG:
    svg = SVG(W, 300, t, "川意 MiChongs — Backend & Systems Developer")
    svg.css.append(
        "@keyframes flow{to{stroke-dashoffset:-560}}"
        "@keyframes drip{to{stroke-dashoffset:-48}}"
        "@keyframes blink{50%{opacity:0}}"
        ".flow{stroke-dasharray:70 490;animation:flow 4.2s linear infinite}"
        ".drip{stroke-dasharray:1.5 10.5;animation:drip 1.6s linear infinite}"
        ".cur{animation:blink 1.05s steps(1) infinite}"
    )
    svg.panel(r=18)
    cid = clip_panel(svg, 18)
    svg.add(f'<g clip-path="url(#{cid})">')
    dot_grid(svg, 700, 150, 300, 220)
    glow(svg, 720, 20, 300, t["a2"])
    glow(svg, 860, 300, 260, t["a3"], 0.8)
    glow(svg, 40, 300, 240, t["a1"], 0.35)
    svg.add("</g>")

    # eyebrow
    svg.add(f'<circle cx="52" cy="54" r="4" fill="{t["ok"]}"/>'
            f'<circle cx="52" cy="54" r="4" fill="none" stroke="{t["ok"]}" stroke-width="1.5">{ping(4, 13)}</circle>')
    svg.text(66, 58.5, "BUILDING IN PUBLIC SINCE 2019", "mono", 11.5, t["sub"], ls=1.6)

    # name lockup
    grad = svg.uid("ng")
    svg.linear(grad, [(0, t["text"], 1), (0.55, t["text"], 1), (1, t["a2"], 1)], 0, 0, 1, 1)
    w = svg.gradient_text(42, 160, "川意", "serif", 96, grad)
    lx = 42 + w + 26
    svg.text(lx, 112, "MiChongs", "sans-sb", 32, t["text"], ls=-0.4)
    svg.text(lx, 142, "Backend & Systems Developer", "sans", 17, t["sub"])
    svg.add(f'<rect x="{lx}" y="152" width="34" height="2" rx="1" fill="{t["a1"]}"/>')

    # typing line
    typing(svg, 46, 214, t)

    # language pills
    x = 46
    for name, color in (("Go", "#00ADD8"), ("Rust", "#DEA584"), ("Kotlin", "#A97BFF"), ("TypeScript", "#3178C6")):
        tw = width(name, "sans-m", 12.5)
        pw = tw + 32
        svg.add(f'<rect x="{x}" y="240" width="{pw:.1f}" height="26" rx="13" fill="{t["chip"]}" stroke="{t["border"]}"/>'
                f'<circle cx="{x + 13}" cy="253" r="3.5" fill="{color}"/>')
        svg.text(x + 22, 257.5, name, "sans-m", 12.5, t["sub"])
        x += pw + 8
    svg.text(x + 6, 257.5, "· UTC+8", "mono", 11.5, t["muted"])

    # 川 — three streams: go, rust, kotlin
    streams = [
        ("M640 44 C643 110 642 170 632 214 C624 246 610 262 592 276", t["a1"], 0.0),
        ("M712 70 C709 110 715 160 712 228", t["a2"], -1.4),
        ("M784 36 C787 110 781 190 786 270", t["a3"], -2.8),
    ]
    sg = svg.uid("sg")
    svg.linear(sg, [(0, t["a1"], 1), (0.5, t["a2"], 1), (1, t["a3"], 1)], 590, 0, 790, 0, user=True)
    fid = svg.uid("f")
    svg.defs.append(f'<filter id="{fid}" x="-50%" y="-50%" width="200%" height="200%">'
                    f'<feGaussianBlur stdDeviation="3"/></filter>')
    for i, (d, color, delay) in enumerate(streams):
        pid = f"st{i}"
        svg.defs.append(f'<path id="{pid}" d="{d}"/>')
        svg.add(f'<use xlink:href="#{pid}" stroke="url(#{sg})" stroke-width="26" stroke-linecap="round" opacity="0.10"/>'
                f'<use xlink:href="#{pid}" stroke="{color}" stroke-width="1.5" opacity="0.35"/>'
                f'<use class="drip" xlink:href="#{pid}" stroke="{color}" stroke-width="2" stroke-linecap="round" '
                f'opacity="0.55" style="animation-delay:{delay * 0.3:.2f}s"/>'
                f'<use class="flow" xlink:href="#{pid}" stroke="{color}" stroke-width="6" stroke-linecap="round" '
                f'filter="url(#{fid})" style="animation-delay:{delay}s"/>'
                f'<use class="flow" xlink:href="#{pid}" stroke="{color}" stroke-width="2.4" stroke-linecap="round" '
                f'style="animation-delay:{delay}s"/>')
        for j in range(2):
            begin = f"{delay - j * 2.1:.1f}s"
            svg.add(f'<circle r="2.6" fill="{t["text"]}"><animateMotion dur="4.2s" begin="{begin}" '
                    f'repeatCount="indefinite"><mpath xlink:href="#{pid}"/></animateMotion></circle>')
    for x, y, label, color in ((592, 276, "go", t["a1"]), (712, 228, "rust", t["a2"]), (786, 270, "kotlin", t["a3"])):
        svg.add(f'<circle cx="{x}" cy="{y}" r="4" fill="{t["panel"]}" stroke="{color}" stroke-width="2"/>')
    svg.text(606, 280, "go", "mono", 11, t["muted"])
    svg.text(726, 232, "rust", "mono", 11, t["muted"])
    svg.text(800, 274, "kotlin", "mono", 11, t["muted"])
    return svg


def typing(svg: SVG, x: float, y: float, t: dict[str, str]) -> None:
    """Type / erase TYPING phrases one after another (SMIL, discrete steps)."""
    size, font = 17, "mono"
    svg.add(f'<path d="M{x + 1} {y - 12.5} l6.5 6.5 -6.5 6.5" stroke="{t["a1"]}" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
    tx = x + 22
    cw = width("M", font, size)
    type_s, erase_s, hold_s, gap_s = 0.065, 0.025, 1.6, 0.35
    slots = []
    for p in TYPING:
        n = len(p)
        slots.append(n * type_s + hold_s + n * erase_s + gap_s)
    total = sum(slots)

    cursor_vals: list[tuple[float, float]] = []
    start = 0.0
    for idx, p in enumerate(TYPING):
        n = len(p)
        frames: list[tuple[float, float]] = [(0.0, 0.0)]
        for i in range(n + 1):
            frames.append((start + i * type_s, i * cw))
        t_hold_end = start + n * type_s + hold_s
        for i in range(n + 1):
            frames.append((t_hold_end + i * erase_s, (n - i) * cw))
        frames.sort()
        key = ";".join(f"{min(ft / total, 1):.5f}" for ft, _ in frames)
        val = ";".join(f"{fv:.1f}" for _, fv in frames)
        cid = svg.uid("ty")
        svg.defs.append(f'<clipPath id="{cid}"><rect x="{tx}" y="{y - 20}" width="0" height="28">'
                        f'<animate attributeName="width" values="{val}" keyTimes="{key}" dur="{total:.2f}s" '
                        f'calcMode="discrete" repeatCount="indefinite"/></rect></clipPath>')
        g, _ = svg.glyph_run(tx, y, p, font, size)
        svg.add(f'<g fill="{svg.t["text"]}" clip-path="url(#{cid})">{g}</g>')
        cursor_vals.extend(frames[1:])
        start += slots[idx]
    cursor_vals = [(0.0, 0.0)] + sorted(cursor_vals)
    key = ";".join(f"{min(ft / total, 1):.5f}" for ft, _ in cursor_vals)
    val = ";".join(f"{tx + fv + 2:.1f}" for _, fv in cursor_vals)
    svg.add(f'<rect class="cur" x="{tx + 2}" y="{y - 15}" width="9" height="19" rx="1.5" fill="{t["a2"]}">'
            f'<animate attributeName="x" values="{val}" keyTimes="{key}" dur="{total:.2f}s" '
            f'calcMode="discrete" repeatCount="indefinite"/></rect>')


def section(t: dict[str, str], idx: int, sec: tuple[str, str, str, str]) -> SVG:
    _, title, zh, hint = sec
    svg = SVG(W, 64, t, f"{idx:02d} {title}")
    svg.text(4, 38, f"{idx:02d}", "mono-b", 13, t["a2"])
    svg.text(26, 38, "/", "mono", 13, t["muted"])
    x = 44 + svg.text(44, 39, title, "sans-sb", 23, t["text"], ls=-0.3)
    svg.text(x + 12, 38.5, zh, "zh", 14, t["muted"])
    svg.text(W - 4, 38, hint, "mono", 11.5, t["muted"], anchor="end")
    gid = svg.uid("hl")
    svg.linear(gid, [(0, t["a1"], 1), (0.18, t["a2"], 0.8), (0.42, t["border"], 1), (1, t["border"], 0.2)])
    svg.add(f'<rect x="4" y="54" width="{W - 8}" height="1" fill="url(#{gid})"/>')
    return svg


def whoami(t: dict[str, str], stats: dict[str, Any]) -> SVG:
    lines = [ln for ln in WHOAMI]
    h = 72 + 30 + len(lines) * 23 + 54
    svg = SVG(W, h, t, "whoami — neofetch style profile card")
    svg.panel(r=16)
    cid = clip_panel(svg)
    svg.add(f'<g clip-path="url(#{cid})">')
    glow(svg, 120, h, 260, t["a1"], 0.5)
    glow(svg, 200, 40, 220, t["a3"], 0.4)
    svg.add(f'<rect x="1" y="1" width="{W - 2}" height="38" fill="{t["faint"]}" opacity="0.6"/></g>'
            f'<rect x="1" y="39" width="{W - 2}" height="1" fill="{t["border"]}"/>')
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        svg.add(f'<circle cx="{24 + i * 18}" cy="20" r="5.5" fill="{c}"/>')
    svg.text(W / 2, 24.5, "chuanyi@michongs: ~ — neofetch", "mono", 11.5, t["muted"], anchor="middle")

    # ASCII 川
    art_size, art_lh = 14, 17
    art_h = len(ASCII_CHUAN) * art_lh
    ay = 40 + (h - 40 - art_h) / 2 + 11
    grad = svg.uid("ag")
    svg.linear(grad, [(0, t["a1"], 1), (0.5, t["a2"], 1), (1, t["a3"], 1)],
               40, ay - 12, 300, ay + art_h, user=True)
    for i, row in enumerate(ASCII_CHUAN):
        if row.strip():
            svg.gradient_text(40, ay + i * art_lh, row, "mono-b", art_size, grad)

    # info column
    x0, y = 330, 76
    svg.text(x0, y, "chuanyi", "mono-b", 15, t["a1"])
    xw = width("chuanyi", "mono-b", 15)
    svg.text(x0 + xw, y, "@", "mono", 15, t["muted"])
    svg.text(x0 + xw + width("@", "mono", 15), y, "michongs", "mono-b", 15, t["a2"])
    svg.add(f'<rect x="{x0}" y="{y + 12}" width="{W - x0 - 40}" height="1" fill="{t["border"]}"/>')
    y += 40
    size = 13.5
    cw = width("M", "mono", size)
    key_cols = 13
    fmt = {
        "uptime": f"{dt.date.today().year - SINCE} years · since {SINCE}",
        "repos": stats["repos"], "stars": stats["stars"], "followers": stats["followers"],
        "contribs": f'{stats["contribs"]:,}',
    }
    for ln in lines:
        if ln is None:
            svg.add(f'<rect x="{x0}" y="{y - 13}" width="{W - x0 - 40}" height="1" fill="{t["border"]}" '
                    f'stroke-dasharray="3 4" opacity="0.8"/>')
            y += 12
            continue
        key, val = ln
        val = val.format(**fmt)
        svg.text(x0, y, key, "mono-b", size, t["a2"])
        dots = key_cols - len(key)
        svg.text(x0 + (len(key) + 1) * cw, y, "." * (dots - 1), "mono", size, t["muted"], attrs=' opacity="0.55"')
        vx = x0 + (key_cols + 1) * cw
        if re.search(r"[一-鿿]", val):
            svg.text(vx, y + 0.5, val, "zh", size + 0.5, t["text"])
        else:
            svg.text(vx, y, val, "mono", size, t["text"])
        y += 23
    y += 6
    for i, c in enumerate(PALETTE):
        svg.add(f'<rect x="{x0 + i * 30}" y="{y}" width="26" height="12" rx="3" fill="{c}"/>')
    return svg


LANG_FALLBACK = {"Rust": "#dea584", "Go": "#00ADD8", "Kotlin": "#A97BFF", "TypeScript": "#3178c6",
                 "JavaScript": "#f1e05a"}


def card(t: dict[str, str], p: dict[str, Any]) -> SVG:
    cw, ch = 430, 156
    svg = SVG(cw, ch, t, f'{p["name"]} — {p["desc"]}')
    lang, color = p["lang"], p["color"]
    svg.panel(w=cw, h=ch, r=14)
    cid = svg.uid("c")
    svg.defs.append(f'<clipPath id="{cid}"><rect x="1" y="1" width="{cw - 2}" height="{ch - 2}" rx="14"/></clipPath>')
    svg.add(f'<g clip-path="url(#{cid})">')
    glow(svg, cw - 30, -10, 170, color, 0.9)
    lg = svg.uid("tl")
    svg.linear(lg, [(0, color, 0), (0.5, color, 0.9), (1, color, 0)])
    svg.add(f'<rect x="40" y="1" width="{cw - 80}" height="1.5" fill="url(#{lg})"/></g>')

    svg.add(f'<path transform="translate(22 25) scale(1.05)" fill="{t["muted"]}" d="{octicon("repo-16")}"/>')
    svg.text(46, 40, p["name"], "sans-sb", 19, t["text"], ls=-0.2)
    star_txt = str(p["stars"])
    sw = width(star_txt, "sans-m", 14)
    svg.text(cw - 22, 39.5, star_txt, "sans-m", 14, t["text"], anchor="end")
    svg.add(f'<path transform="translate({cw - 22 - sw - 21:.1f} 26.5) scale(1)" fill="{t["warm"]}" d="{octicon("star-fill-16")}"/>')

    for i, line in enumerate(wrap(p["desc"], "sans", 13.5, cw - 44, 2)):
        svg.text(22, 70 + i * 20, line, "sans", 13.5, t["sub"])

    y = 130
    svg.add(f'<circle cx="28" cy="{y - 4.5}" r="5.5" fill="{color}"/>')
    x = 40 + svg.text(40, y, lang, "sans-m", 12.5, t["sub"])
    svg.add(f'<path transform="translate({x + 14:.1f} {y - 12}) scale(0.95)" fill="{t["muted"]}" d="{octicon("repo-forked-16")}"/>')
    x += 32 + svg.text(x + 32, y, str(p["forks"]), "sans-m", 12.5, t["sub"])
    x += 16
    for tag in p["tags"]:
        tw = width(tag, "mono", 11)
        if x + tw + 16 > cw - 18:
            break
        svg.add(f'<rect x="{x:.1f}" y="{y - 15}" width="{tw + 16:.1f}" height="21" rx="10.5" fill="{t["chip"]}" stroke="{t["border"]}"/>')
        svg.text(x + 8, y - 0.5, tag, "mono", 11, t["muted"])
        x += tw + 22
    return svg


def icon_svg(spec: str, theme: str, t: dict[str, str], prefix: str) -> str:
    """Return the inner markup of a 256×256 skill-style tile."""
    spec = spec.replace("{T}", theme.capitalize()).replace("{fg}", t["fg"].lstrip("#"))
    if spec.startswith("si:"):
        _, slug, hexc = spec.split(":")
        raw = (HERE / "icons" / "simple" / f"{slug}.svg").read_text(encoding="utf-8")
        d = re.search(r'<path d="([^"]+)"', raw).group(1)
        return (f'<rect width="256" height="256" rx="60" fill="{t["tile"]}"/>'
                f'<path transform="translate(56 56) scale(6)" fill="#{hexc}" d="{d}"/>')
    if spec.startswith("txt:"):
        _, label, hexc = spec.split(":")
        return f'<rect width="256" height="256" rx="60" fill="{t["tile"]}"/>@@TXT:{label}:{hexc}@@'
    raw = (HERE / "icons" / "skill" / f"{spec}.svg").read_text(encoding="utf-8")
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", raw, flags=re.S)
    ids = set(re.findall(r'id="([^"]+)"', inner))
    for i in sorted(ids, key=len, reverse=True):
        inner = inner.replace(f'id="{i}"', f'id="{prefix}{i}"').replace(f"url(#{i})", f"url(#{prefix}{i})")
    return inner


def stack(t: dict[str, str], theme: str) -> SVG:
    bw, bh, gap = 434, 128, 12
    svg = SVG(W, bh * 2 + gap, t, "Toolbox — " + ", ".join(n for _, items in STACK for n, _ in items))
    for gi, (label, items) in enumerate(STACK):
        bx, by = (gi % 2) * (bw + gap), (gi // 2) * (bh + gap)
        svg.panel(bx, by, bw, bh, r=14)
        svg.text(bx + 20, by + 28, label.upper(), "mono-b", 10.5, t["muted"], ls=1.4)
        svg.text(bx + bw - 20, by + 28, f"{len(items):02d}", "mono", 10.5, t["muted"], anchor="end",
                 attrs=' opacity="0.6"')
        size = 44
        step = (bw - 40 - size) / (len(items) - 1)
        for ii, (name, spec) in enumerate(items):
            ix, iy = bx + 20 + ii * step, by + 42
            inner = icon_svg(spec, theme, t, f"i{gi}{ii}")
            m = re.search(r"@@TXT:([^:]+):([^@]+)@@", inner)
            if m:
                g, _ = svg.glyph_run(128, 150, m.group(1), "sans-sb", 74, anchor="middle", ls=-2)
                inner = inner.replace(m.group(0), f'<g fill="#{m.group(2)}">{g}</g>')
            svg.add(f'<svg x="{ix:.1f}" y="{iy}" width="{size}" height="{size}" viewBox="0 0 256 256">{inner}</svg>')
            svg.text(ix + size / 2, by + 108, name, "sans", 10.5, t["sub"], anchor="middle")
    return svg


def river(t: dict[str, str]) -> SVG:
    h = 324
    svg = SVG(W, h, t, "The river so far — " + "; ".join(f"{y} {e}" for y, e, _, _ in RIVER))
    svg.css.append(
        "@keyframes rflow{to{stroke-dashoffset:-60}}"
        ".rflow{stroke-dasharray:1.5 13.5;animation:rflow 2.4s linear infinite}"
    )
    svg.panel(r=16)
    cid = clip_panel(svg)
    svg.add(f'<g clip-path="url(#{cid})">')
    glow(svg, 760, 162, 260, t["a3"], 0.5)
    glow(svg, 120, 162, 240, t["a1"], 0.4)
    dot_grid(svg, 440, 162, 460, 170, 24)
    svg.add("</g>")

    cy, amp, half = 162, 24, 165
    xs = [100 + i * half for i in range(len(RIVER))]

    def ry(x: float) -> float:
        return cy - amp * math.cos(math.pi * (x - 100) / half)

    pts = [(x, ry(x)) for x in range(18, W - 17, 15)]
    d = catmull_rom(pts)
    rg = svg.uid("rg")
    svg.linear(rg, [(0, t["a1"], 1), (0.5, t["a2"], 1), (1, t["a3"], 1)], 18, 0, W - 18, 0, user=True)
    fade = svg.uid("rf")
    svg.linear(fade, [(0, "#fff", 0), (0.06, "#fff", 1), (0.94, "#fff", 1), (1, "#fff", 0)], 0, 0, W, 0, user=True)
    mid = svg.uid("rm")
    svg.defs.append(f'<mask id="{mid}"><rect width="{W}" height="{h}" fill="url(#{fade})"/></mask>')
    svg.defs.append(f'<path id="rv" d="{d}"/>')
    svg.add(f'<g mask="url(#{mid})">'
            f'<use xlink:href="#rv" stroke="url(#{rg})" stroke-width="30" stroke-linecap="round" opacity="0.10"/>'
            f'<use xlink:href="#rv" stroke="url(#{rg})" stroke-width="14" stroke-linecap="round" opacity="0.10"/>'
            f'<use xlink:href="#rv" stroke="url(#{rg})" stroke-width="2.5"/>'
            f'<use class="rflow" xlink:href="#rv" stroke="{t["text"]}" stroke-width="2.2" stroke-linecap="round" opacity="0.55"/>')
    for i in range(4):
        svg.add(f'<circle r="3" fill="{t["text"]}" opacity="0.9"><animateMotion dur="9s" begin="{-i * 2.25:.2f}s" '
                f'repeatCount="indefinite"><mpath xlink:href="#rv"/></animateMotion></circle>')
    svg.add("</g>")

    accents = [t["a1"], t["a1"], t["a2"], t["a3"], t["a3"]]
    for i, ((year, title, zh, detail), x) in enumerate(zip(RIVER, xs)):
        y = ry(x)
        c = accents[i]
        last = i == len(RIVER) - 1
        if last:
            svg.add(f'<circle cx="{x}" cy="{y:.1f}" r="7" fill="none" stroke="{c}" stroke-width="2">{ping(7, 20)}</circle>')
        svg.add(f'<circle cx="{x}" cy="{y:.1f}" r="7.5" fill="{t["panel"]}" stroke="{c}" stroke-width="2.5"/>'
                f'<circle cx="{x}" cy="{y:.1f}" r="3" fill="{c}"/>')
        up = i % 2 == 0
        if up:
            svg.add(f'<rect x="{x - .5}" y="{y - 26:.1f}" width="1" height="14" fill="{c}" opacity="0.5"/>')
            base = y - 104
        else:
            svg.add(f'<rect x="{x - .5}" y="{y + 12:.1f}" width="1" height="14" fill="{c}" opacity="0.5"/>')
            base = y + 46
        svg.text(x, base, year, "mono-b", 12.5, c, anchor="middle", ls=0.5)
        svg.text(x, base + 21, title, "sans-sb", 15.5, t["text"], anchor="middle", ls=-0.2)
        svg.text(x, base + 40, zh, "zh", 12, t["sub"], anchor="middle")
        svg.text(x, base + 57, detail, "mono", 10.5, t["muted"], anchor="middle")
    return svg


def footer(t: dict[str, str]) -> SVG:
    svg = SVG(W, 128, t, "Started in 2019. Still learning, still building. 始于热爱，忠于长期主义")
    svg.css.append("@keyframes fflow{to{stroke-dashoffset:-44}}"
                   ".fflow{stroke-dasharray:10 34;animation:fflow 1.8s linear infinite}")
    cx = W / 2
    marks = ((-16, 8, 46, -7, t["a1"]), (0, 16, 38, 0, t["a2"]), (16, 4, 50, 0, t["a3"]))
    for i, (dx, top, bot, sweep, c) in enumerate(marks):
        x = cx + dx
        d = f"M{x} {top} C{x + 1} {top + 14} {x + .5} {bot - 12} {x + sweep} {bot}"
        svg.add(f'<path d="{d}" stroke="{c}" stroke-width="3" stroke-linecap="round" opacity="0.3"/>'
                f'<path class="fflow" d="{d}" stroke="{c}" stroke-width="3" stroke-linecap="round" '
                f'style="animation-delay:{-i * 0.6:.1f}s"/>')
    svg.text(cx, 84, "Started in 2019. Still learning, still building.", "sans-m", 15, t["sub"], anchor="middle")
    svg.text(cx, 108, "始于热爱，忠于长期主义 · 用作品记录成长", "zh", 12.5, t["muted"], anchor="middle")
    return svg


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection { contributionCalendar { totalContributions } }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC) {
      pageInfo { hasNextPage endCursor }
      nodes { name isFork stargazerCount forkCount pushedAt primaryLanguage { name color } }
    }
  }
}
"""


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    return subprocess.check_output(["gh", "auth", "token"]).decode().strip()


def fetch() -> dict[str, Any]:
    tok, after, repos = token(), None, []
    while True:
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": QUERY, "variables": {"login": USER, "after": after}}).encode(),
            headers={"Authorization": f"bearer {tok}", "User-Agent": f"{USER}-profile"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
        if payload.get("errors"):
            raise SystemExit(f"GraphQL error: {payload['errors']}")
        user = payload["data"]["user"]
        page = user["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return {
        "repos": sum(not r["isFork"] for r in repos),
        "stars": sum(r["stargazerCount"] for r in repos),  # forks included, like the 3D calendar
        "followers": user["followers"]["totalCount"],
        "contribs": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "by_name": {r["name"]: r for r in repos},
    }


def featured(stats: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in PROJECTS:
        r = stats["by_name"].get(p["repo"])
        if not r:
            print(f"::warning::{p['repo']} not found among public repositories", file=sys.stderr)
            continue
        lang = (r["primaryLanguage"] or {}).get("name") or "—"
        color = (r["primaryLanguage"] or {}).get("color") or LANG_FALLBACK.get(lang, "#8b949e")
        out.append({**p, "name": r["name"], "stars": r["stargazerCount"], "forks": r["forkCount"],
                    "pushed": r["pushedAt"], "lang": lang, "color": color})
    out.sort(key=lambda p: p["pushed"], reverse=True)
    out.sort(key=lambda p: -p["stars"])
    return out[:MAX_FEATURED]


# ----------------------------------------------------------------------
# README
# ----------------------------------------------------------------------
START, END = "<!-- FEATURED:START -->", "<!-- FEATURED:END -->"


def picture(name: str, alt: str, width_attr: str = "100%") -> str:
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}/assets/{name}-dark.svg">'
            f'<source media="(prefers-color-scheme: light)" srcset="{RAW}/assets/{name}-light.svg">'
            f'<img alt="{html.escape(alt)}" src="{RAW}/assets/{name}-dark.svg" width="{width_attr}"></picture>')


def update_readme(projects: list[dict[str, Any]]) -> None:
    rows = []
    for i in range(0, len(projects), 2):
        pair = projects[i:i + 2]
        cells = [f'<a href="https://github.com/{USER}/{p["name"]}">'
                 f'{picture("card-" + p["name"].lower(), p["name"] + " — " + p["desc"], "49%")}</a>' for p in pair]
        rows.append("\n".join(cells))
    block = f"{START}\n<p align=\"center\">\n" + "\n<br/>\n".join(rows) + f"\n</p>\n{END}"
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    if new != text:
        readme.write_text(new, encoding="utf-8")
        print("  README featured block updated: " + ", ".join(f"{p['name']}★{p['stars']}" for p in projects))


def main() -> int:
    OUT.mkdir(exist_ok=True)
    stats = fetch()
    projects = featured(stats)
    print(f"repos={stats['repos']} stars={stats['stars']} followers={stats['followers']} contribs={stats['contribs']}")
    keep = set()
    for theme, t in THEMES.items():
        panels = {
            "hero": hero(t),
            "whoami": whoami(t, stats),
            "stack": stack(t, theme),
            "river": river(t),
            "footer": footer(t),
        }
        for i, sec in enumerate(SECTIONS, 1):
            panels[f"h-{sec[0]}"] = section(t, i, sec)
        for p in projects:
            panels[f"card-{p['name'].lower()}"] = card(t, p)
        for name, svg in panels.items():
            save(f"{name}-{theme}.svg", svg)
            keep.add(f"{name}-{theme}.svg")
    for stale in OUT.glob("card-*.svg"):
        if stale.name not in keep:
            stale.unlink()
            print(f"  removed {stale.name}")
    update_readme(projects)
    return 0


if __name__ == "__main__":
    sys.exit(main())
