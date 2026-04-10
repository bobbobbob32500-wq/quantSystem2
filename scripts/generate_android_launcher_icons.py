#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate Android launcher icons from a local SVG file."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image


def find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Microsoft Edge not found. Please install Edge first.")


def file_uri(path: Path) -> str:
    posix = path.resolve().as_posix()
    return f"file:///{quote(posix)}"


def render_svg_to_png(svg_path: Path, output_png: Path, size: int = 1024) -> None:
    edge = find_edge()
    html = (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<style>html,body{margin:0;width:100%;height:100%;background:transparent;}"
        "img{display:block;width:100%;height:100%;object-fit:contain;}</style>"
        "</head><body>"
        f"<img src='{file_uri(svg_path)}' alt='icon'/>"
        "</body></html>"
    )

    with tempfile.TemporaryDirectory(prefix="icon_render_") as tmp:
        html_file = Path(tmp) / "render.html"
        html_file.write_text(html, encoding="utf-8")
        command = [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size={0},{0}".format(size),
            "--default-background-color=00000000",
            f"--screenshot={output_png}",
            file_uri(html_file),
        ]
        subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Android launcher icons from SVG.")
    parser.add_argument(
        "--svg",
        default="android_app/app_icon.svg",
        help="Source SVG file path.",
    )
    parser.add_argument(
        "--project",
        default="android_app",
        help="Android project root that contains app/src/main/res.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    svg_path = (root / args.svg).resolve()
    if not svg_path.exists():
        raise FileNotFoundError(f"SVG not found: {svg_path}")

    project_root = (root / args.project).resolve()
    res_dir = project_root / "app" / "src" / "main" / "res"
    if not res_dir.exists():
        raise FileNotFoundError(f"Android res dir not found: {res_dir}")

    base_png = project_root / "app_icon_rendered.png"
    render_svg_to_png(svg_path=svg_path, output_png=base_png, size=1024)

    sizes = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    image = Image.open(base_png).convert("RGBA")
    for folder, px in sizes.items():
        target_dir = res_dir / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        resized = image.resize((px, px), Image.LANCZOS)
        resized.save(target_dir / "ic_launcher.png", format="PNG")
        resized.save(target_dir / "ic_launcher_round.png", format="PNG")

    print("Launcher icons generated:")
    for folder, px in sizes.items():
        print(f"- {folder}: {px}x{px}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
