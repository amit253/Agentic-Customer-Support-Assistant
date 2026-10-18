"""Render docs/diagrams/*.mmd to SVG and PNG with the pinned mermaid-cli image.

Mermaid needs a headless browser, so rendering runs in the official
mermaid-cli Docker image instead of installing Node and Chromium locally.
On Windows the system fonts are mounted read-only so text is measured with
Segoe UI, the font the diagrams ask for.

    python scripts/render_diagrams.py            # every diagram
    python scripts/render_diagrams.py 03-memory  # names starting with a prefix
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "docs" / "diagrams"
IMAGE = "minlag/mermaid-cli:12.0.0"
WINDOWS_FONTS = Path("C:/Windows/Fonts")


def render(source: Path) -> None:
    mounts = ["-v", f"{DIAGRAMS}:/data"]
    if WINDOWS_FONTS.is_dir():
        mounts += ["-v", f"{WINDOWS_FONTS}:/usr/share/fonts/windows:ro"]
    for suffix, extra in ((".svg", []), (".png", ["-s", "2"])):
        target = source.with_suffix(suffix).name
        subprocess.run(
            ["docker", "run", "--rm", *mounts, IMAGE,
             "-i", f"/data/{source.name}", "-o", f"/data/{target}",
             "-c", "/data/mermaid-config.json", "-b", "white", *extra],
            check=True,
            capture_output=True,
        )
        print(f"rendered docs/diagrams/{target}")


def main() -> None:
    prefixes = sys.argv[1:]
    sources = sorted(DIAGRAMS.glob("*.mmd"))
    for source in sources:
        if not prefixes or any(source.name.startswith(prefix) for prefix in prefixes):
            render(source)


if __name__ == "__main__":
    main()
