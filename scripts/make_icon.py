"""Generate assets/icon.ico.

Kept as a script rather than a hand-drawn asset so the icon can be adjusted
without a graphics editor. The .ico it produces is committed, so a normal build
does not need to run this.

    python scripts\\make_icon.py

The mark is the conventional translate glyph: the Han character 文 over a Latin
A — one script becoming another, which is exactly what the app does. It is drawn
from stroke paths rather than set in a typeface, because no font can be relied
on to be installed on a build machine, and because the strokes need to stay
legible when the icon is 16 pixels across.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "assets" / "icon.ico"

# Drawn once at this size and downsampled, which antialiases far better than
# drawing the small sizes directly.
CANVAS = 1024

INK = (17, 17, 17, 255)

#: Stroke weight. Heavy enough to survive being scaled to 16 pixels, where a
#: hairline would disappear into the background entirely.
STROKE = 62

#: Sizes Windows actually asks for, smallest first.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _curve(points: list[tuple[float, float]], steps: int = 48) -> list[tuple[float, float]]:
    """Sample a quadratic Bézier through three control points.

    The falling strokes of 文 are curved, not straight; drawing them as
    straight lines reads as a plain X rather than as the character.
    """
    (x0, y0), (x1, y1), (x2, y2) = points
    sampled = []
    for step in range(steps + 1):
        t = step / steps
        inverse = 1 - t
        x = inverse * inverse * x0 + 2 * inverse * t * x1 + t * t * x2
        y = inverse * inverse * y0 + 2 * inverse * t * y1 + t * t * y2
        sampled.append((x, y))
    return sampled


def _stroke(canvas: ImageDraw.ImageDraw, points: list[tuple[float, float]]) -> None:
    """Draw one stroke with round ends, the way a brush would leave it.

    Stamped as a run of overlapping discs rather than drawn with `line()`.
    A thick polyline of many short segments comes out visibly scalloped —
    PIL mitres each segment separately — and the falling strokes of 文 are
    exactly that shape.
    """
    radius = STROKE / 2

    def disc(x: float, y: float) -> None:
        canvas.ellipse((x - radius, y - radius, x + radius, y + radius), fill=INK)

    for (x0, y0), (x1, y1) in pairwise(points):
        span = max(abs(x1 - x0), abs(y1 - y0))
        # One stamp per pixel of travel: any sparser and the edge ripples.
        for step in range(int(span) + 1):
            t = step / max(int(span), 1)
            disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    disc(*points[-1])


def draw() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)

    # -- 文, upper left ----------------------------------------------------

    # The 亠 lid: a short vertical tick above a long horizontal bar.
    _stroke(canvas, [(392, 96), (392, 178)])
    _stroke(canvas, [(150, 236), (628, 236)])

    # The 乂 beneath it. The left-falling stroke is the long one and carries
    # the character; the right-falling stroke is shorter and tucks under the A.
    _stroke(canvas, _curve([(516, 300), (392, 470), (146, 606)]))
    _stroke(canvas, _curve([(268, 336), (368, 452), (486, 548)]))

    # -- A, lower right ----------------------------------------------------

    apex = (628, 424)
    _stroke(canvas, [(398, 918), apex])
    _stroke(canvas, [apex, (858, 918)])
    _stroke(canvas, [(486, 742), (770, 742)])

    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = draw()
    image.save(OUTPUT, format="ICO", sizes=[(size, size) for size in SIZES])
    # A PNG alongside it, for the README and any future installer artwork.
    image.resize((256, 256), Image.LANCZOS).save(OUTPUT.with_suffix(".png"))
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
