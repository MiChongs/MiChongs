#!/usr/bin/env python3
"""
Build the SVG panels of the MiChongs profile README.

Every panel is drawn twice, dark and light, into assets/, and README.md picks
one with <picture>. Text is converted to glyph outlines from the subset fonts
in fonts/, so the panels render the same everywhere without web fonts.
Repository stats and the contribution calendar come from the GitHub GraphQL
API, and the featured project block in README.md is rewritten in star order.

Run locally:   pip install -r .github/profile/requirements.txt
               GITHUB_TOKEN=$(gh auth token) python .github/profile/build.py
Run in CI:     .github/workflows/profile.yml
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
# Content
# ----------------------------------------------------------------------
USER = "MiChongs"
SINCE = 2019

ROLE = "Backend and systems developer"
LANGS = [("Go", "#00ADD8"), ("Rust", "#DEA584"), ("Kotlin", "#A97BFF"), ("TypeScript", "#3178C6")]
ZONE = "UTC+8"

# neofetch card; values may use {years} {repos} {forked} {stars} {followers} {contribs}
NEOFETCH = [
    ("OS", "Kubuntu 26.04 LTS x86_64"),
    ("DE", "Plasma 6.6 (Wayland)"),
    ("Shell", "bash 5.3"),
    ("Editor", "Zed, VS Code, Android Studio"),
    ("Uptime", "{years} years (since 2019)"),
    None,
    ("Languages", "Go, Rust, Kotlin, TypeScript"),
    ("Work", "proxy cores, gateways, PAM, platforms"),
    ("Stack", "Gin, gRPC, Temporal, NATS, PostgreSQL"),
    None,
    ("Repos", "{repos} own, {forked} forks"),
    ("Stars", "{stars}"),
    ("Followers", "{followers}"),
    ("Contribs", "{contribs} in the last year"),
]

# Whitelist for the project cards; the top MAX_FEATURED by stars are shown.
MAX_FEATURED = 10
PROJECTS: list[dict[str, Any]] = [
    {"repo": "sing-box", "tags": ["go", "proxy", "ebpf"],
     "desc": "Adds a Smart outbound group, XHTTP, VLESS Encryption, QUICX and an eBPF inbound to upstream sing-box."},
    {"repo": "WutherCore", "tags": ["rust", "tun", "proxy"],
     "desc": "Cross-platform proxy core in Rust with TUN and TPROXY capture, policy routing, DNS, subscriptions and an API."},
    {"repo": "Wayfort", "tags": ["go", "next.js", "bastion"],
     "desc": "Bastion host that runs in the browser. SSH, RDP, VNC, database and file sessions without a client."},
    {"repo": "user_system", "tags": ["node.js", "mysql", "auth"],
     "desc": "User auth and account management, written while I was moving from apps to backend work."},
    {"repo": "aegis", "tags": ["go", "temporal", "nats"],
     "desc": "Multi-tenant user platform on Gin, PostgreSQL, Redis and NATS, with Temporal for workflows."},
    {"repo": "Frida-RS", "tags": ["kernelsu", "frida", "webui"],
     "desc": "Frida Server as a KernelSU module, with a Rust supervisor, a Material 3 WebUI and builds for four ABIs."},
    {"repo": "ChuanyiHooker", "tags": ["xposed", "android", "kavaref"],
     "desc": "Xposed module host. Each target app gets its own hooker, picked up at runtime."},
    {"repo": "Proxy-RS", "tags": ["sing-box", "ratatui", "cli"],
     "desc": "Manager for sing-box and mihomo with system services, a Ratatui TUI, a tray icon and a CLI."},
    {"repo": "singbox-board", "tags": ["ratatui", "daemon", "tui"],
     "desc": "Root daemon and terminal dashboard for sing-box: core versions, configs, subscriptions, containers."},
    {"repo": "cronet-rs", "tags": ["cronet", "http3", "ffi"],
     "desc": "Rust bindings for Chromium Cronet, including the H2/H3 bidirectional streams NaiveProxy uses."},
    {"repo": "Readme", "tags": ["next.js", "prisma", "cms"],
     "desc": "Personal homepage generator and blog CMS on Next.js, React, Prisma and Tailwind CSS."},
]

# (label, icon); icon = skill-icons file stem, "si:<slug>:<hex>" or "txt:<label>:<hex>"
STACK = [
    ("Languages", [("Go", "GoLang"), ("Rust", "Rust"), ("Kotlin", "Kotlin-{T}"),
                   ("TypeScript", "TypeScript"), ("Java", "Java-{T}"), ("Python", "Python-{T}"),
                   ("Bash", "Bash-{T}")]),
    ("Backend & data", [("Gin", "si:gin:008ECF"), ("gRPC", "txt:gRPC:2DA6B0"),
                        ("Temporal", "si:temporal:{fg}"), ("NATS", "si:natsdotio:27AAE1"),
                        ("PostgreSQL", "PostgreSQL-{T}"), ("Redis", "Redis-{T}"), ("MySQL", "MySQL-{T}")]),
    ("Systems, mobile & web", [("Tokio", "si:tokio:{fg}"), ("Ratatui", "si:ratatui:{fg}"),
                               ("Android", "AndroidStudio-{T}"), ("Compose", "si:jetpackcompose:4285F4"),
                               ("Next.js", "NextJS-{T}"), ("React", "React-{T}"),
                               ("Tailwind", "TailwindCSS-{T}")]),
    ("Infra & tooling", [("Linux", "Linux-{T}"), ("Docker", "Docker"), ("Nginx", "Nginx"),
                         ("Actions", "GithubActions-{T}"), ("Cloudflare", "Cloudflare-{T}"),
                         ("Gradle", "Gradle-{T}"), ("Git", "Git")]),
]

RIVER = [
    ("2019", "First line of code", "learning the basics"),
    ("2021", "Joined GitHub", "reading open source code"),
    ("2022-23", "Android and Kotlin", "apps and UI work"),
    ("2024-25", "Moved to backend", "user_system, auth, APIs"),
    ("2026", "Systems and infra", "sing-box fork, WutherCore"),
]

# (key, title, note on the right)
SECTIONS = [
    ("about", "About", ""),
    ("work", "Projects", "sorted by stars"),
    ("stack", "Stack", ""),
    ("river", "Timeline", "since 2019"),
    ("activity", "Contributions", ""),
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
# Design tokens: ink greys plus one vermilion
# ----------------------------------------------------------------------
THEMES: dict[str, dict[str, Any]] = {
    "dark": {
        "panel": "#0d1117", "border": "#262c35", "line": "#3d4450", "faint": "#151a21",
        "text": "#e6edf3", "sub": "#9ca6b1", "muted": "#68717c", "chip": "#151b23",
        "fg": "#ffffff", "tile": "#242938", "zhu": "#f2704f",
        "ink": ["#161b22", "#2a313b", "#4b5461", "#868f9b", "#d2d8df"],
    },
    "light": {
        "panel": "#ffffff", "border": "#dde2e7", "line": "#c3cad2", "faint": "#f6f8fa",
        "text": "#1f2328", "sub": "#57606a", "muted": "#8c959f", "chip": "#f6f8fa",
        "fg": "#000000", "tile": "#F4F2ED", "zhu": "#c63b24",
        "ink": ["#ebeef1", "#c9d0d7", "#97a0aa", "#58616b", "#22272e"],
    },
}
# Konsole's Breeze colour scheme, shown the way neofetch prints its colour blocks
BREEZE = ["#232627", "#ed1515", "#11d116", "#f67400", "#1d99f3", "#9b59b6", "#1abc9c", "#fcfcfc"]
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
W = 880  # every full-width panel shares this viewBox width


# ----------------------------------------------------------------------
# Fonts to glyph outlines
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
        print(f"::warning::text needs {len(lines)} lines, only {max_lines} fit: {s}", file=sys.stderr)
        last = lines[max_lines - 1]
        while width(last + "...", font, size) > max_w:
            last = last.rsplit(" ", 1)[0]
        lines = lines[: max_lines - 1] + [last.rstrip(",;:") + "..."]
    return lines


# ----------------------------------------------------------------------
# SVG document
# ----------------------------------------------------------------------
@dataclass
class SVG:
    w: float
    h: float
    t: dict[str, Any]
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

    def linear(self, gid: str, stops: list[tuple[float, str, float]],
               x1: float = 0, y1: float = 0, x2: float = 1, y2: float = 0, user: bool = False) -> None:
        units = ' gradientUnits="userSpaceOnUse"' if user else ""
        s = "".join(f'<stop offset="{o}" stop-color="{c}" stop-opacity="{a}"/>' for o, c, a in stops)
        self.defs.append(f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{units}>{s}</linearGradient>')

    def panel(self, x: float = 0, y: float = 0, w: float | None = None, h: float | None = None,
              r: float = 14) -> None:
        w = self.w if w is None else w
        h = self.h if h is None else h
        self.add(f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="{r}" '
                 f'fill="{self.t["panel"]}" stroke="{self.t["border"]}"/>')

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
# Shared pieces
# ----------------------------------------------------------------------
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
def hero(t: dict[str, Any]) -> SVG:
    h = 224
    svg = SVG(W, h, t, f"{USER}, {ROLE.lower()}")
    svg.panel()

    svg.text(54, 106, USER, "sans-sb", 58, t["text"], ls=-1.8)
    svg.text(57, 146, ROLE, "sans", 19, t["sub"], ls=-0.1)
    x = 58
    for name, color in LANGS:
        svg.add(f'<circle cx="{x + 4}" cy="179.5" r="4" fill="{color}"/>')
        x += 14 + svg.text(x + 14, 184, name, "sans-m", 13.5, t["sub"]) + 22
    svg.add(f'<rect x="{x - 4}" y="171" width="1" height="17" fill="{t["border"]}"/>')
    svg.text(x + 14, 184, ZONE, "mono", 12, t["muted"])
    return svg


def section(t: dict[str, Any], title: str, note: str = "") -> SVG:
    svg = SVG(W, 60, t, title)
    svg.add(f'<rect x="4" y="22" width="9" height="9" rx="2" fill="{t["zhu"]}"/>')
    svg.text(24, 34, title, "sans-sb", 21, t["text"], ls=-0.3)
    if note:
        svg.text(W - 4, 34, note, "sans", 12.5, t["muted"], anchor="end")
    svg.add(f'<rect x="4" y="51" width="{W - 8}" height="1" fill="{t["border"]}"/>')
    return svg


def neofetch(t: dict[str, Any], stats: dict[str, Any]) -> SVG:
    size, lh, mono = 13.5, 22, "mono"
    cw = width("M", mono, size)
    info_h = 44 + sum(12 if ln is None else lh for ln in NEOFETCH) + 30
    art_h = len(ASCII_CHUAN) * 17
    body_top = 98
    h = body_top + max(info_h, art_h) + 74
    svg = SVG(W, h, t, "neofetch: " + ", ".join(f"{k} {v}" for k, v in (ln for ln in NEOFETCH if ln)))
    svg.css.append("@keyframes blink{50%{opacity:0}}.cur{animation:blink 1.1s steps(1) infinite}")
    svg.panel(r=12)

    # Breeze-style title bar
    cid = svg.uid("c")
    svg.defs.append(f'<clipPath id="{cid}"><rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="12"/></clipPath>')
    svg.add(f'<rect x="1" y="1" width="{W - 2}" height="36" fill="{t["faint"]}" clip-path="url(#{cid})"/>'
            f'<rect x="1" y="37" width="{W - 2}" height="1" fill="{t["border"]}"/>'
            f'<path transform="translate(16 11)" fill="{t["muted"]}" d="{octicon("terminal-16")}"/>')
    svg.text(W / 2, 23.5, "chuanyi@michongs: ~", "sans-m", 12, t["muted"], anchor="middle")
    icon = f'stroke="{t["muted"]}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
    svg.add(f'<path d="M{W - 84} 17 l4.5 4.5 4.5 -4.5" {icon}/>'
            f'<path d="M{W - 58} 21.5 l4.5 -4.5 4.5 4.5" {icon}/>'
            f'<path d="M{W - 31} 15 l8 8 m0 -8 l-8 8" {icon}/>')

    def prompt(y: float, cmd: str) -> float:
        x = 32 + svg.text(32, y, "chuanyi@michongs", "mono-b", size, t["zhu"])
        x += svg.text(x, y, ":", mono, size, t["text"])
        x += svg.text(x, y, "~", "mono-b", size, t["sub"])
        x += svg.text(x, y, "$ ", mono, size, t["text"])
        if cmd:
            x += svg.text(x, y, cmd, mono, size, t["text"])
        return x

    prompt(68, "neofetch")

    ay = body_top + 12 + (max(info_h, art_h) - art_h) / 2
    for i, row in enumerate(ASCII_CHUAN):
        if row.strip():
            svg.text(40, ay + i * 17, row, "mono-b", 14, t["zhu"])

    x0, y = 340, body_top + 14
    svg.text(x0, y, "chuanyi", "mono-b", size, t["zhu"])
    xw = width("chuanyi", "mono-b", size)
    svg.text(x0 + xw, y, "@", mono, size, t["text"])
    svg.text(x0 + xw + cw, y, "michongs", "mono-b", size, t["zhu"])
    y += lh
    svg.text(x0, y, "-" * 16, mono, size, t["muted"])
    y += lh
    fmt = {
        "years": dt.date.today().year - SINCE, "repos": stats["repos"], "forked": stats["forked"],
        "stars": stats["stars"], "followers": stats["followers"], "contribs": f'{stats["contribs"]:,}',
    }
    for ln in NEOFETCH:
        if ln is None:
            y += 12
            continue
        key, val = ln
        kx = x0 + svg.text(x0, y, key, "mono-b", size, t["zhu"])
        kx += svg.text(kx, y, ":", mono, size, t["text"])
        svg.text(kx + cw, y, val.format(**fmt), mono, size, t["text"])
        y += lh
    y += 2
    for i, c in enumerate(BREEZE):
        svg.add(f'<rect x="{x0 + i * cw * 3:.1f}" y="{y - 12}" width="{cw * 3:.1f}" height="16" fill="{c}"/>')

    x = prompt(h - 30, "")
    svg.add(f'<rect class="cur" x="{x:.1f}" y="{h - 43}" width="{cw:.1f}" height="17" fill="{t["text"]}"/>')
    return svg


LANG_FALLBACK = {"Rust": "#dea584", "Go": "#00ADD8", "Kotlin": "#A97BFF", "TypeScript": "#3178c6",
                 "JavaScript": "#f1e05a"}


def card(t: dict[str, Any], p: dict[str, Any]) -> SVG:
    cw, ch = 430, 156
    svg = SVG(cw, ch, t, f'{p["name"]}: {p["desc"]}')
    svg.panel(w=cw, h=ch, r=12)

    svg.add(f'<path transform="translate(22 25)" fill="{t["muted"]}" '
            f'd="{octicon("repo-forked-16" if p["parent"] else "repo-16")}"/>')
    svg.text(46, 39, p["name"], "sans-sb", 18, t["text"], ls=-0.2)
    star_txt = str(p["stars"])
    sw = width(star_txt, "sans-m", 13.5)
    svg.text(cw - 22, 38.5, star_txt, "sans-m", 13.5, t["sub"], anchor="end")
    svg.add(f'<path transform="translate({cw - 22 - sw - 21:.1f} 26)" fill="{t["muted"]}" d="{octicon("star-fill-16")}"/>')

    y = 70
    if p["parent"]:
        svg.text(46, 59, f'forked from {p["parent"]}', "sans", 12, t["muted"])
        y = 84
    for i, line in enumerate(wrap(p["desc"], "sans", 13.5, cw - 44, 2)):
        svg.text(22, y + i * 20, line, "sans", 13.5, t["sub"])

    y = 136
    svg.add(f'<circle cx="27" cy="{y - 4.5}" r="5" fill="{p["color"]}"/>')
    x = 38 + svg.text(38, y, p["lang"], "sans-m", 12.5, t["sub"])
    svg.add(f'<path transform="translate({x + 14:.1f} {y - 12})" fill="{t["muted"]}" d="{octicon("repo-forked-16")}"/>')
    x += 34 + svg.text(x + 34, y, str(p["forks"]), "sans-m", 12.5, t["sub"])
    x += 14
    for tag in p["tags"]:
        tw = width(tag, "mono", 11)
        if x + tw + 16 > cw - 18:
            break
        svg.add(f'<rect x="{x:.1f}" y="{y - 15}" width="{tw + 16:.1f}" height="21" rx="10.5" '
                f'fill="{t["chip"]}" stroke="{t["border"]}"/>')
        svg.text(x + 8, y - 0.5, tag, "mono", 11, t["muted"])
        x += tw + 22
    return svg


def icon_svg(spec: str, theme: str, t: dict[str, Any], prefix: str) -> str:
    """Return the inner markup of a 256x256 skill-style tile."""
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


def stack(t: dict[str, Any], theme: str) -> SVG:
    bw, bh, gap = 434, 128, 12
    svg = SVG(W, bh * 2 + gap, t, "Stack: " + ", ".join(n for _, items in STACK for n, _ in items))
    for gi, (label, items) in enumerate(STACK):
        bx, by = (gi % 2) * (bw + gap), (gi // 2) * (bh + gap)
        svg.panel(bx, by, bw, bh, r=12)
        svg.text(bx + 20, by + 29, label, "sans-m", 12.5, t["sub"])
        size = 44
        step = (bw - 40 - size) / (len(items) - 1)
        for ii, (name, spec) in enumerate(items):
            ix, iy = bx + 20 + ii * step, by + 44
            inner = icon_svg(spec, theme, t, f"i{gi}{ii}")
            m = re.search(r"@@TXT:([^:]+):([^@]+)@@", inner)
            if m:
                g, _ = svg.glyph_run(128, 150, m.group(1), "sans-sb", 74, anchor="middle", ls=-2)
                inner = inner.replace(m.group(0), f'<g fill="#{m.group(2)}">{g}</g>')
            svg.add(f'<svg x="{ix:.1f}" y="{iy}" width="{size}" height="{size}" viewBox="0 0 256 256">{inner}</svg>')
            svg.text(ix + size / 2, by + 110, name, "sans", 10.5, t["muted"], anchor="middle")
    return svg


def river(t: dict[str, Any]) -> SVG:
    h = 296
    svg = SVG(W, h, t, "Timeline: " + "; ".join(f"{y} {title}" for y, title, _ in RIVER))
    svg.panel()

    cy, amp, half = 150, 16, 165
    xs = [100 + i * half for i in range(len(RIVER))]

    def ry(x: float) -> float:
        return cy - amp * math.cos(math.pi * (x - 100) / half)

    pts = [(x, ry(x)) for x in range(24, W - 23, 15)]
    fade = svg.uid("rf")
    svg.linear(fade, [(0, "#fff", 0), (0.07, "#fff", 1), (0.93, "#fff", 1), (1, "#fff", 0)], 0, 0, W, 0, user=True)
    mid = svg.uid("rm")
    svg.defs.append(f'<mask id="{mid}"><rect width="{W}" height="{h}" fill="url(#{fade})"/></mask>'
                    f'<path id="rv" d="{catmull_rom(pts)}"/>')
    svg.add(f'<g mask="url(#{mid})"><use xlink:href="#rv" stroke="{t["line"]}" stroke-width="1.5"/>'
            f'<circle r="2.5" fill="{t["zhu"]}"><animateMotion dur="16s" repeatCount="indefinite">'
            f'<mpath xlink:href="#rv"/></animateMotion></circle></g>')

    for i, ((year, title, detail), x) in enumerate(zip(RIVER, xs)):
        y = ry(x)
        last = i == len(RIVER) - 1
        if last:
            svg.add(f'<circle cx="{x}" cy="{y:.1f}" r="10" fill="none" stroke="{t["zhu"]}" opacity="0.35"/>'
                    f'<circle cx="{x}" cy="{y:.1f}" r="5" fill="{t["zhu"]}"/>')
        else:
            svg.add(f'<circle cx="{x}" cy="{y:.1f}" r="5" fill="{t["panel"]}" stroke="{t["sub"]}" stroke-width="1.5"/>')
        if i % 2 == 0:
            svg.add(f'<rect x="{x - .5}" y="{y - 28:.1f}" width="1" height="14" fill="{t["line"]}"/>')
            base = y - 80
        else:
            svg.add(f'<rect x="{x - .5}" y="{y + 14:.1f}" width="1" height="14" fill="{t["line"]}"/>')
            base = y + 48
        svg.text(x, base, year, "mono-b", 12, t["zhu"] if last else t["muted"], anchor="middle", ls=0.4)
        svg.text(x, base + 22, title, "sans-sb", 15.5, t["text"], anchor="middle", ls=-0.2)
        svg.text(x, base + 41, detail, "sans", 12, t["muted"], anchor="middle")
    return svg


LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def streaks(days: list[dict[str, Any]]) -> tuple[int, int]:
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] else 0
        longest = max(longest, run)
    current = 0
    # today may still be empty, so count back from yesterday in that case
    for d in reversed(days[:-1] if days and not days[-1]["contributionCount"] else days):
        if not d["contributionCount"]:
            break
        current += 1
    return longest, current


def calendar(t: dict[str, Any], stats: dict[str, Any]) -> SVG:
    weeks = stats["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    total = stats["contribs"]
    best = max(days, key=lambda d: (d["contributionCount"], d["date"]))
    longest, current = streaks(days)
    bd = dt.date.fromisoformat(best["date"])

    h, cell, pitch = 236, 12, 15
    gx, gy = W - 24 - len(weeks) * pitch + 3, 96
    svg = SVG(W, h, t, f"{total} contributions in the last year, longest streak {longest} days")
    svg.css.append("@keyframes ink{from{opacity:0}}.d{animation:ink .6s ease-out backwards}")
    svg.panel()

    x = 24 + svg.text(24, 52, f"{total:,}", "sans-sb", 30, t["text"], ls=-0.6)
    svg.text(x + 9, 51, "contributions in the last year", "sans", 14, t["sub"])
    notes = [("longest streak", f"{longest} days"), ("current streak", f"{current} days"),
             ("busiest day", f"{best['contributionCount']} on {MONTHS[bd.month - 1]} {bd.day}")]
    rx = W - 24
    for label, value in reversed(notes):
        rx -= svg.text(rx, 51, value, "sans-m", 12.5, t["text"], anchor="end") + 6
        rx -= svg.text(rx, 51, label, "sans", 12.5, t["muted"], anchor="end") + 24

    months: list[tuple[int, int]] = []  # (column, month) where a month begins
    for wi, w in enumerate(weeks):
        m = dt.date.fromisoformat(w["contributionDays"][-1]["date"]).month
        if not months or months[-1][1] != m:
            months.append((wi, m))
    if len(months) > 1 and months[1][0] - months[0][0] < 3:
        months.pop(0)
    for wi, m in months:
        if wi < len(weeks) - 2:
            svg.text(gx + wi * pitch, gy - 10, MONTHS[m - 1], "sans", 11, t["muted"])
    for r, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        svg.text(24, gy + r * pitch + 10, label, "sans", 10.5, t["muted"])

    ink = t["ink"]
    cells = []
    for wi, w in enumerate(weeks):
        for d in w["contributionDays"]:
            fill = t["zhu"] if d is best else ink[LEVELS[d["contributionLevel"]]]
            cells.append(f'<rect class="d" x="{gx + wi * pitch}" y="{gy + d["weekday"] * pitch}" width="{cell}" '
                         f'height="{cell}" rx="2.5" fill="{fill}" style="animation-delay:{wi * 14}ms"/>')
    svg.add("".join(cells))

    lx = W - 24
    lx -= svg.text(lx, 222, "More", "sans", 11, t["muted"], anchor="end") + 8
    for c in reversed(ink):
        lx -= cell
        svg.add(f'<rect x="{lx}" y="212" width="{cell}" height="{cell}" rx="2.5" fill="{c}"/>')
        lx -= 3
    svg.text(lx - 5, 222, "Less", "sans", 11, t["muted"], anchor="end")
    svg.add(f'<rect x="{gx}" y="212" width="{cell}" height="{cell}" rx="2.5" fill="{t["zhu"]}"/>')
    svg.text(gx + cell + 8, 222, "busiest day", "sans", 11, t["muted"])
    return svg


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date weekday contributionCount contributionLevel } }
      }
    }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name isFork stargazerCount forkCount pushedAt
        primaryLanguage { name color }
        parent { nameWithOwner }
      }
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
    cal = user["contributionsCollection"]["contributionCalendar"]
    return {
        "repos": sum(not r["isFork"] for r in repos),
        "forked": sum(r["isFork"] for r in repos),
        "stars": sum(r["stargazerCount"] for r in repos),  # forks included
        "followers": user["followers"]["totalCount"],
        "contribs": cal["totalContributions"],
        "weeks": cal["weeks"],
        "by_name": {r["name"]: r for r in repos},
    }


def featured(stats: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in PROJECTS:
        r = stats["by_name"].get(p["repo"])
        if not r:
            print(f"::warning::{p['repo']} not found among public repositories", file=sys.stderr)
            continue
        lang = (r["primaryLanguage"] or {}).get("name") or "Other"
        color = (r["primaryLanguage"] or {}).get("color") or LANG_FALLBACK.get(lang, "#8b949e")
        out.append({**p, "name": r["name"], "stars": r["stargazerCount"], "forks": r["forkCount"],
                    "pushed": r["pushedAt"], "lang": lang, "color": color,
                    "parent": (r["parent"] or {}).get("nameWithOwner")})
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
                 f'{picture("card-" + p["name"].lower(), p["name"] + ": " + p["desc"], "49%")}</a>' for p in pair]
        rows.append("\n".join(cells))
    block = f"{START}\n<p align=\"center\">\n" + "\n<br/>\n".join(rows) + f"\n</p>\n{END}"
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    if new != text:
        readme.write_text(new, encoding="utf-8")
        print("  README featured block updated: " + ", ".join(f"{p['name']} {p['stars']}" for p in projects))


def main() -> int:
    OUT.mkdir(exist_ok=True)
    stats = fetch()
    projects = featured(stats)
    print(f"repos={stats['repos']} forked={stats['forked']} stars={stats['stars']} "
          f"followers={stats['followers']} contribs={stats['contribs']}")
    keep = set()
    for theme, t in THEMES.items():
        panels = {
            "hero": hero(t),
            "about": neofetch(t, stats),
            "stack": stack(t, theme),
            "river": river(t),
            "activity": calendar(t, stats),
        }
        for key, title, note in SECTIONS:
            panels[f"h-{key}"] = section(t, title, note)
        for p in projects:
            panels[f"card-{p['name'].lower()}"] = card(t, p)
        for name, svg in panels.items():
            save(f"{name}-{theme}.svg", svg)
            keep.add(f"{name}-{theme}.svg")
    for stale in OUT.glob("*.svg"):
        if stale.name not in keep:
            stale.unlink()
            print(f"  removed {stale.name}")
    update_readme(projects)
    return 0


if __name__ == "__main__":
    sys.exit(main())
