"""Generate assets/icon.ico.

Kept as a script rather than a hand-drawn asset so the icon can be adjusted
without a graphics editor. The .ico it produces is committed, so a normal build
does not need to run this.

    python scripts\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "assets" / "icon.ico"

# Drawn once at this size and downsampled, which antialiases far better than
# drawing the small sizes directly.
CANVAS = 1024

BACKGROUND = (32, 78, 158, 255)
PAGE = (255, 255, 255, 255)
PAGE_EDGE = (214, 222, 236, 255)
RULE = (150, 168, 198, 255)
ACCENT = (247, 181, 56, 255)

#: Sizes Windows actually asks for, smallest first.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)

    # Rounded square backdrop, inset so the corners are not clipped.
    canvas.rounded_rectangle((40, 40, CANVAS - 40, CANVAS - 40), radius=200, fill=BACKGROUND)

    # A page with a folded corner: the most legible "document" shape there is
    # once it is 16 pixels across.
    left, top, right, bottom = 250, 190, 774, 834
    fold = 150
    page = [
        (left, top),
        (right - fold, top),
        (right, top + fold),
        (right, bottom),
        (left, bottom),
    ]
    canvas.polygon(page, fill=PAGE)
    canvas.line([*page, (left, top)], fill=PAGE_EDGE, width=8)
    # The fold itself.
    canvas.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)],
        fill=PAGE_EDGE,
    )

    # Lines of text on the page, with the lower half in the accent colour to
    # say "the same text, now different".
    line_left, line_right = left + 70, right - 70
    y = top + 230
    for index in range(5):
        width = line_right if index != 4 else line_left + (line_right - line_left) * 0.55
        canvas.rounded_rectangle(
            (line_left, y, width, y + 34),
            radius=17,
            fill=ACCENT if index >= 3 else RULE,
        )
        y += 76

    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = draw()
    image.save(
        OUTPUT,
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )
    # A PNG alongside it, for the README and any future installer artwork.
    image.resize((256, 256), Image.LANCZOS).save(OUTPUT.with_suffix(".png"))
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
