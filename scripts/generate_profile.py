#!/usr/bin/env python3
"""Render an accessible, self-contained SVG terminal profile from public data."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from fetch_stats import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
THEMES = {
    "dark": dict(bg="#17111b", header="#241a29", border="#463043", text="#fff6fc",
                 muted="#d9b8ce", accent="#ff9dce", blue="#ffc4e1", portrait="#fff1f8"),
    "light": dict(bg="#211823", header="#302134", border="#65475a", text="#fff9fd",
                  muted="#e0bed3", accent="#ffabd6", blue="#ffd0e8", portrait="#fff1f8"),
}


def shorten(value: object, length: int) -> str:
    # Remote strings are plain text and XML-escaped before entering the SVG.
    value = " ".join(str(value or "").split())
    return textwrap.shorten(value, width=length, placeholder="...") if len(value) > length else value


def download_avatar(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "avatars.githubusercontent.com":
        raise ValueError("Portrait source must be a public GitHub avatar URL")
    request = urllib.request.Request(url, headers={"User-Agent": "GitHub-Terminal-Profile"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000:
        raise ValueError("Avatar exceeds the 5 MB size limit")
    return payload


def portrait_from_image(image: Image.Image) -> dict:
    # Honor phone-camera orientation and flatten transparency onto dark plum.
    oriented = ImageOps.exif_transpose(image).convert("RGBA")
    canvas = Image.new("RGB", oriented.size, "#17111b")
    canvas.paste(oriented, mask=oriented.getchannel("A"))
    image = ImageOps.fit(canvas, (672, 672), method=Image.Resampling.LANCZOS)
    image = image.resize((112, 70), Image.Resampling.LANCZOS)
    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
    grayscale = grayscale.filter(ImageFilter.UnsharpMask(radius=0.8, percent=150, threshold=2))
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    indexed = image.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    color_table = indexed.getpalette()
    colors = ["#b74b85", "#e77ab4", "#ffaad4", "#ffd4eb", "#fff5fc"]
    color_indexes = []
    for index in range(16):
        original = color_table[index * 3:index * 3 + 3]
        # Pink midtones and white highlights preserve the hair and eyes.
        luminance = sum(channel * weight for channel, weight in zip(original, (0.2126, 0.7152, 0.0722))) / 255
        color_indexes.append(min(4, int(luminance * 5)))
    ramp = " .,:;irsXA253hMHGS#9B&@"
    rows, color_rows = [], []
    for y in range(image.height):
        row, color_row = [], []
        for x in range(image.width):
            lightness = (grayscale.getpixel((x, y)) / 255) ** 0.88
            edge = edges.getpixel((x, y)) / 255 if 0 < x < 111 and 0 < y < 69 else 0
            density = min(1, 0.87 * lightness + 0.13 * edge)
            row.append(ramp[round(density * (len(ramp) - 1))])
            color_row.append(color_indexes[indexed.getpixel((x, y))])
        rows.append("".join(row))
        color_rows.append(color_row)
    return {"version": 2, "columns": 112, "lines": 70, "rows": rows, "colors": colors, "color_rows": color_rows}


def demo_portrait() -> dict:
    """An original geometric robot fixture; no downloaded artwork or account."""
    image = Image.new("RGB", (672, 672), "#241a29")
    draw = ImageDraw.Draw(image)
    draw.ellipse((86, 58, 586, 558), fill="#493044")
    draw.line((336, 98, 336, 168), fill="#ffaad4", width=14)
    draw.ellipse((310, 72, 362, 124), fill="#fff5fc")
    draw.rounded_rectangle((148, 166, 524, 484), radius=84, fill="#ffd4eb")
    draw.rounded_rectangle((180, 212, 492, 354), radius=40, fill="#302134")
    for x in (256, 416):
        draw.ellipse((x - 25, 248, x + 25, 306), fill="#fff5fc")
        draw.ellipse((x - 9, 254, x + 9, 278), fill="#ffaad4")
    draw.arc((264, 338, 408, 436), 8, 172, fill="#493044", width=12)
    draw.rounded_rectangle((184, 506, 488, 656), radius=42, fill="#e77ab4")
    draw.rounded_rectangle((256, 536, 416, 604), radius=14, fill="#fff5fc")
    return portrait_from_image(image)


def normalize_config(config: dict) -> dict:
    config = dict(config)
    username = str(config.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
        raise ValueError("Set username in profile.json to your real GitHub login (not YOUR_USERNAME)")
    defaults = dict(name=username, role="Developer / Builder", focus="Learning / Creating",
                    stack="", now="Building something new", tagline="Small ideas. Thoughtful code.")
    config = {**defaults, **config, "username": username}
    repository = os.environ.get("GITHUB_REPOSITORY") or config.get("repository") or f"{username}/{username}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be in owner/repository form")
    config["repository"] = repository
    config["branch"] = os.environ.get("DEFAULT_BRANCH") or config.get("branch", "main")
    return config


def validate_portrait(portrait: dict, source: dict) -> None:
    if portrait.get("version") != 2 or portrait.get("source") != source:
        raise ValueError("Portrait cache belongs to a different source. Run again without --offline.")
    if len(portrait.get("rows", [])) != 70 or any(len(row) != 112 for row in portrait["rows"]):
        raise ValueError("Portrait cache has an invalid character grid")
    if len(portrait.get("color_rows", [])) != 70 or any(len(row) != 112 for row in portrait["color_rows"]):
        raise ValueError("Portrait cache has an invalid color grid")
    if not portrait.get("colors") or any(not isinstance(index, int) or not 0 <= index < len(portrait["colors"])
                                         for row in portrait["color_rows"] for index in row):
        raise ValueError("Portrait cache has an invalid palette index")
    if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in portrait["colors"]):
        raise ValueError("Portrait cache has an invalid palette color")


def render(config: dict, stats: dict, portrait: dict, mode: str, mobile: bool = False) -> str:
    palette = THEMES[mode]
    width, height = (640, 1132) if mobile else (1120, 670)
    rows = portrait["rows"]
    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(config["name"])}: terminal-style GitHub profile</title>',
        '<desc id="desc">ASCII portrait, personal introduction and public GitHub statistics. '
        'Uptime is GitHub account age. Stars and forks are totals on owned public repositories.</desc>',
        '<style>text {font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",Menlo,monospace;}'
        + ''.join(f'.p{i}{{fill:{color};}}' for i, color in enumerate(portrait["colors"])) + '</style>',
        f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="16" fill="{palette["bg"]}" stroke="{palette["border"]}"/>',
        f'<path d="M17 1H{width-17}Q{width-1} 1 {width-1} 17V57H1V17Q1 1 17 1Z" fill="{palette["header"]}"/>',
        f'<path d="M1 57H{width-1}" stroke="{palette["border"]}"/>',
    ]

    def text(x: float, y: float, content: object, size: float = 15, color: str = "text", bold: bool = False, anchor: str = "start") -> None:
        fragments.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{palette[color]}" '
                         f'font-weight="{"700" if bold else "400"}" text-anchor="{anchor}">{escape(str(content))}</text>')

    for x, color in [(28, "#ff5f57"), (48, "#febc2e"), (68, "#28c840")]:
        fragments.append(f'<circle cx="{x}" cy="29" r="5.5" fill="{color}"/>')
    text(width / 2, 34, "~/" + config["username"] + " / neofetch", 12, "muted", anchor="middle")
    if mobile:
        portrait_x, portrait_y, portrait_step, portrait_size = 156, 98, 4.69, 4.7
        portrait_caption_y = 458
        column_x, title_y = 34, 530
        fragments.append('<rect x="144" y="80" width="352" height="356" rx="10" fill="#130f16"/>')
    else:
        portrait_x, portrait_y, portrait_step, portrait_size = 30, 145, 4.69, 4.7
        portrait_caption_y = 526
        column_x, title_y = 420, 113
        fragments.append('<rect x="20" y="114" width="348" height="386" rx="10" fill="#130f16"/>')
        fragments.append(f'<path d="M386 97V559" stroke="{palette["border"]}" stroke-dasharray="3 6"/>')

    for index, row in enumerate(rows):
        # Explicit width avoids changes in fallback monospace font metrics.
        portrait_width = 328
        color_row = portrait["color_rows"][index]
        runs = []
        start = 0
        for end in range(1, len(row) + 1):
            if end == len(row) or color_row[end] != color_row[start]:
                runs.append(f'<tspan class="p{color_row[start]}">{escape(row[start:end])}</tspan>')
                start = end
        fragments.append(f'<text x="{portrait_x}" y="{portrait_y+index*portrait_step:.2f}" font-size="{portrait_size}" '
                         f'fill="{palette["portrait"]}" xml:space="preserve" textLength="{portrait_width}" '
                         f'lengthAdjust="spacingAndGlyphs">{"".join(runs)}</text>')
    center = 194 if not mobile else width / 2
    text(center, portrait_caption_y, config["name"], 21, "text", True, "middle")
    text(center, portrait_caption_y + 26, "@" + config["username"], 12, "muted", anchor="middle")
    text(column_x, title_y, config["username"] + "@github", 20, "accent", True)
    fragments.append(f'<path d="M{column_x} {title_y+20}H{width-36}" stroke="{palette["border"]}"/>')
    languages = [label.replace("Jupyter Notebook", "Jupyter") for label in list(stats.get("languages", {}))[:5]]
    details = [
        ("Role", shorten(config["role"], 43)),
        ("Focus", shorten(config["focus"], 43)),
        ("Stack", shorten(config.get("stack") or " / ".join(languages) or "Building something new", 55)),
        ("Uptime", f'{stats["account_age_days"]:,} days on GitHub'),
        ("Now", shorten(config.get("now", "From idea to production"), 43)),
    ]
    for index, (label, value) in enumerate(details):
        y = title_y + 63 + index * 33
        text(column_x, y, label, 14, "blue", True)
        text(column_x + 83, y, value, 14, "text")

    stats_y = title_y + 248
    text(column_x, stats_y, "// DEMO / SAMPLE NUMBERS" if stats.get("is_demo") else "// PUBLIC GITHUB STATS", 12, "muted")
    metrics = [
        (stats["public_repos"], "PUBLIC REPOS"), (stats["owned_stars"], "STARS EARNED"),
        (stats["followers"], "FOLLOWERS"), (stats["owned_forks"], "FORKS RECEIVED"),
        (stats["following"], "FOLLOWING"), (stats["created_at"][:4], "JOINED GITHUB"),
    ]
    available_width = width - column_x - 36
    for index, (value, label) in enumerate(metrics):
        x = column_x + (index % 3) * (available_width / 3)
        y = stats_y + 47 + (index // 3) * 68
        formatted = f"{value:,}" if isinstance(value, int) else value
        text(x, y, formatted, 27, "accent", True)
        text(x, y + 21, label, 10, "muted")
    text(column_x, stats_y + 193, "$ keep building_", 15, "blue")
    footer_y = height - 78
    fragments.append(f'<path d="M28 {footer_y}H{width-28}" stroke="{palette["border"]}"/>')
    text(32, footer_y + 30, shorten(config["tagline"], 68 if not mobile else 55), 12, "muted")
    fetched_at = datetime.fromisoformat(stats["fetched_at"].replace("Z", "+00:00"))
    refreshed = fetched_at.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M UTC+8")
    text(32, footer_y + 54, "OFFLINE DEMO / SAMPLE DATA" if stats.get("is_demo") else "PUBLIC DATA / DAILY REFRESH", 9, "muted")
    text(width - 32, footer_y + 54, "UPDATED " + refreshed, 9, "muted", anchor="end")
    fragments.append("</svg>\n")
    return "\n".join(fragments)



if __name__ == "__main__":
    from profile_cli import main
    try:
        main(sys.modules[__name__])
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"Could not generate profile: {error}", file=sys.stderr)
        raise SystemExit(1)
