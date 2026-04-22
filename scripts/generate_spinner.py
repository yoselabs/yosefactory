"""Generate assets/spinner.gif — a minimal dot-ring loading spinner.

One-shot build tool. Run when the visual needs tweaking; the GIF itself
is checked in so the engine doesn't regenerate on every commit.

Usage:
    uv run python scripts/generate_spinner.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = 24
DOTS = 8
RADIUS = 9
DOT_RADIUS = 2
FRAME_MS = 90
OUTPUT = Path(__file__).parent.parent / "assets" / "spinner.gif"


def _frame(active: int) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = SIZE // 2
    for i in range(DOTS):
        angle = 2 * math.pi * i / DOTS - math.pi / 2
        x = cx + int(RADIUS * math.cos(angle))
        y = cy + int(RADIUS * math.sin(angle))
        # Trailing fade: active dot fully opaque, each preceding dot
        # dims by ~1/DOTS. Gives the visual of a rotating tail.
        steps_behind = (active - i) % DOTS
        opacity = max(40, 220 - steps_behind * 22)
        color = (80, 120, 200, opacity)
        draw.ellipse(
            (
                x - DOT_RADIUS,
                y - DOT_RADIUS,
                x + DOT_RADIUS,
                y + DOT_RADIUS,
            ),
            fill=color,
        )
    return img


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [_frame(i) for i in range(DOTS)]
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=2,
        transparency=0,
    )
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
