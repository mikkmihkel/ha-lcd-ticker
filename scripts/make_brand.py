"""Draw the LCD Ticker brand images with Pillow (no fonts needed).

Run from the repository root:

    .venv/bin/python scripts/make_brand.py

Writes icon.png (256x256), icon@2x.png (512x512) and logo.png (256x256) to
custom_components/lcd_ticker/brand/.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components/lcd_ticker/brand"

PANEL = "#C9D4B8"
BORDER = "#2F3A2F"
INK = "#1E1E1E"

# Design grid: 256 x 256. Everything is scaled from it.
GRID = 256
SCALE = 4  # draw at 4x, then downsample for smooth edges

# Seven-segment layout: segments a (top), b (top right), c (bottom right),
# d (bottom), e (bottom left), f (top left), g (middle).
SEGMENTS = {
    "0": "abcdef",
    "5": "acdfg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def segment_rects(x: float, y: float, w: float, h: float, t: float) -> dict:
    """Return the rectangles of one digit cell at (x, y) with size w x h."""
    mid = y + (h - t) / 2
    return {
        "a": (x + t, y, x + w - t, y + t),
        "b": (x + w - t, y, x + w, mid + t),
        "c": (x + w - t, mid, x + w, y + h),
        "d": (x + t, y + h - t, x + w - t, y + h),
        "e": (x, mid, x + t, y + h),
        "f": (x, y, x + t, mid + t),
        "g": (x + t, mid, x + w - t, mid + t),
    }


def draw_digit(draw: ImageDraw.ImageDraw, ch: str, x, y, w, h, t, s) -> None:
    rects = segment_rects(x, y, w, h, t)
    for seg in SEGMENTS[ch]:
        x0, y0, x1, y1 = rects[seg]
        draw.rectangle([x0 * s, y0 * s, x1 * s - 1, y1 * s - 1], fill=INK)


def draw_dot(draw: ImageDraw.ImageDraw, x, y, t, s) -> None:
    draw.rectangle([x * s, y * s, (x + t) * s - 1, (y + t) * s - 1], fill=INK)


def draw_face(draw: ImageDraw.ImageDraw, x, y, s) -> None:
    """A tiny ^_^ made of lines, about 40 x 16 in design units."""
    w = 5.0 * s
    # left eye ^
    draw.line(
        [
            ((x) * s, (y + 12) * s),
            ((x + 8) * s, (y + 3) * s),
            ((x + 16) * s, (y + 12) * s),
        ],
        fill=INK,
        width=int(w),
        joint="curve",
    )
    # mouth _
    draw.line(
        [((x + 18) * s, (y + 13) * s), ((x + 26) * s, (y + 13) * s)],
        fill=INK,
        width=int(w),
    )
    # right eye ^
    draw.line(
        [
            ((x + 28) * s, (y + 12) * s),
            ((x + 36) * s, (y + 3) * s),
            ((x + 44) * s, (y + 12) * s),
        ],
        fill=INK,
        width=int(w),
        joint="curve",
    )


def draw_percent_text(draw: ImageDraw.ImageDraw, x, y, s) -> None:
    """Small '98%' made of small segments, bottom right."""
    w, h, t, gap = 16, 30, 5, 5
    for i, ch in enumerate("98"):
        draw_digit(draw, ch, x + i * (w + gap), y, w, h, t, s)
    px = x + 2 * (w + gap)
    # percent sign: two small squares and a diagonal
    draw.rectangle([px * s, y * s, (px + 9) * s - 1, (y + 9) * s - 1], fill=INK)
    draw.rectangle(
        [(px + 14) * s, (y + 21) * s, (px + 23) * s - 1, (y + 30) * s - 1], fill=INK
    )
    draw.line(
        [((px + 22) * s, (y + 1) * s), ((px + 1) * s, (y + 29) * s)],
        fill=INK,
        width=int(4 * s),
    )


def make(size: int) -> Image.Image:
    s = SCALE * size / GRID
    big = int(size * SCALE)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # panel with a dark rounded border
    draw.rounded_rectangle(
        [8 * s, 8 * s, 248 * s - 1, 248 * s - 1], radius=40 * s, fill=BORDER
    )
    draw.rounded_rectangle(
        [18 * s, 18 * s, 238 * s - 1, 238 * s - 1], radius=30 * s, fill=PANEL
    )

    # big "5.7": two digits, a dot between
    w, h, t = 54, 92, 15
    y = 40
    x5 = 32
    draw_digit(draw, "5", x5, y, w, h, t, s)
    draw_dot(draw, x5 + w + 8, y + h - t, t, s)
    draw_digit(draw, "7", x5 + w + 8 + t + 8, y, w, h, t, s)

    # small 98% bottom right
    draw_percent_text(draw, 104, 156, s)

    # tiny face bottom left
    draw_face(draw, 30, 165, s)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make(256).save(OUT / "icon.png")
    make(512).save(OUT / "icon@2x.png")
    make(256).save(OUT / "logo.png")


if __name__ == "__main__":
    main()
