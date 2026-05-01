#!/usr/bin/env python3
"""
Update the Featured Projects section in README.md, ordered by GitHub stars.

Reads the project whitelist below, queries star counts via the `gh` CLI,
sorts descending, and rewrites the content between the FEATURED markers.

Run locally:   python3 .github/scripts/update_featured.py
Run in CI:     handled by .github/workflows/update-featured.yml
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# Project whitelist  (edit here to add / remove projects)
# ----------------------------------------------------------------------
PROJECTS: list[dict[str, Any]] = [
    {
        "repo": "MiChongs/aegis",
        "desc": "High-performance multi-tenant user platform with workflow orchestration.",
        "tech": ["Go", "Gin", "PostgreSQL", "Redis", "NATS", "Temporal"],
        "logo": "go",
        "color": "00ADD8",
    },
    {
        "repo": "MiChongs/sing-box",
        "desc": "The universal proxy platform — personal fork tracking upstream.",
        "tech": ["Go", "Networking", "Proxy"],
        "logo": "go",
        "color": "00ADD8",
    },
    {
        "repo": "MiChongs/Leaf-IDE",
        "desc": "Modern Android IDE supporting web and native projects.",
        "tech": ["Kotlin", "Android"],
        "logo": "kotlin",
        "color": "7F52FF",
    },
    {
        "repo": "MiChongs/user_system",
        "desc": "User authentication and management system.",
        "tech": ["Backend", "MySQL", "Redis"],
        "logo": None,
        "color": "38BDF8",
    },
    {
        "repo": "MiChongs/box.app",
        "desc": "Android application project.",
        "tech": ["Kotlin", "Android"],
        "logo": "kotlin",
        "color": "7F52FF",
    },
]

START_MARKER = "<!-- FEATURED:START -->"
END_MARKER = "<!-- FEATURED:END -->"


def fetch_stars(repo: str) -> int:
    out = subprocess.check_output(
        ["gh", "api", f"repos/{repo}", "--jq", ".stargazers_count"],
        env={**os.environ},
    ).decode().strip()
    return int(out)


def render_card(p: dict[str, Any]) -> str:
    repo: str = p["repo"]
    name = repo.split("/", 1)[1]
    tech_md = " &middot; ".join(f"`{t}`" for t in p["tech"])
    logo = p.get("logo")
    color = p.get("color", "38BDF8")
    logo_part = f"&logo={logo}&logoColor=white" if logo else "&logoColor=white"

    return (
        f"### [{name}](https://github.com/{repo})\n\n"
        f"{p['desc']}\n\n"
        f"<p>\n"
        f'  <img alt="Stars" src="https://img.shields.io/github/stars/{repo}'
        f"?style=flat-square&logo=github&logoColor=white&label=Stars&color=F59E0B&labelColor=0d1117\" />\n"
        f'  <img alt="Last Commit" src="https://img.shields.io/github/last-commit/{repo}'
        f"?style=flat-square&logo=git&logoColor=white&label=Updated&color=8B5CF6&labelColor=0d1117\" />\n"
        f'  <img alt="Top Language" src="https://img.shields.io/github/languages/top/{repo}'
        f"?style=flat-square{logo_part}&color={color}&labelColor=0d1117\" />\n"
        f"</p>\n\n"
        f"{tech_md}"
    )


def main() -> int:
    enriched: list[dict[str, Any]] = []
    for p in PROJECTS:
        try:
            stars = fetch_stars(p["repo"])
        except subprocess.CalledProcessError as exc:
            print(
                f"::warning::Failed to fetch stars for {p['repo']}: {exc}",
                file=sys.stderr,
            )
            continue
        enriched.append({**p, "stars": stars})

    if not enriched:
        print("::error::No projects could be fetched", file=sys.stderr)
        return 1

    enriched.sort(key=lambda x: -x["stars"])

    body = "\n\n---\n\n".join(render_card(p) for p in enriched)
    block = f"{START_MARKER}\n\n{body}\n\n{END_MARKER}"

    readme = Path("README.md")
    text = readme.read_text(encoding="utf-8")

    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )
    if not pattern.search(text):
        print(
            f"::error::Markers {START_MARKER} ... {END_MARKER} not found in README.md",
            file=sys.stderr,
        )
        return 1

    new_text = pattern.sub(block, text)
    if new_text == text:
        print("README already up to date.")
        return 0

    readme.write_text(new_text, encoding="utf-8")
    print("Featured Projects sorted by stars:")
    for p in enriched:
        print(f"  {p['stars']:>4}  {p['repo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
