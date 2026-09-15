"""Samples the colours of a rendered page.

Pages that carry a real text layer do not need this: the PDF states the colour
of every span, and the extractor keeps it. It is OCR'd pages that need it —
there the only evidence of what colour the text was is the picture itself.
"""

from __future__ import annotations

from collections.abc import Sequence

import pymupdf

from .layout import Rect

Colour = tuple[float, float, float]

WHITE: Colour = (1.0, 1.0, 1.0)
BLACK: Colour = (0.0, 0.0, 0.0)

#: High enough that a glyph stem is two or three pixels wide, which is what it
#: takes to find the colour the text was actually printed in: at 36dpi a 10pt
#: stem is sub-pixel and averages with the paper, so black body copy reads back
#: as mid-grey and the translation is redrawn washed out. A4 at 150dpi is about
#: 6MB, and only one page is held at a time.
SAMPLING_DPI = 150.0

#: Upper bound on how many pixels are inspected per block. Dense enough to land
#: inside the glyphs, cheap enough not to matter.
_MAXIMUM_SAMPLES_PER_AXIS = 64


class PageColourSampler:
    """Reads back the colours of a page so replacement text can be painted in
    a colour that matches what was there before."""

    def __init__(self, page: pymupdf.Page, dpi: float = SAMPLING_DPI) -> None:
        self._scale = dpi / 72.0
        matrix = pymupdf.Matrix(self._scale, self._scale)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
        self._samples = pixmap.samples
        self._width = pixmap.width
        self._height = pixmap.height
        self._stride = pixmap.stride
        self._components = pixmap.n

    # -- public ------------------------------------------------------------

    def background_around(self, rect: Rect) -> Colour:
        """The dominant colour immediately surrounding a rectangle.

        Sampled from a ring outside the text rather than from within it,
        because inside the rectangle the glyphs themselves are a large part of
        the ink.
        """
        margin = max(rect.height * 0.35, 3.0)
        samples: list[tuple[int, int, int]] = []

        def row(y: float) -> None:
            step = max(rect.width / 12, 1.0)
            x = rect.x0
            while x <= rect.x1:
                pixel = self._pixel(x, y)
                if pixel is not None:
                    samples.append(pixel)
                x += step

        def column(x: float) -> None:
            step = max(rect.height / 6, 1.0)
            y = rect.y0
            while y <= rect.y1:
                pixel = self._pixel(x, y)
                if pixel is not None:
                    samples.append(pixel)
                y += step

        row(rect.y0 - margin)
        row(rect.y1 + margin)
        column(rect.x0 - margin)
        column(rect.x1 + margin)

        if not samples:
            return WHITE
        # A mode-by-bucket is more faithful than a mean: averaging a white
        # background against a dark rule line yields grey, which is visible.
        return _dominant(samples)

    def ink_inside(self, rect: Rect, background: Colour) -> Colour:
        """The colour the text in a rectangle was most likely set in.

        Picks whichever extreme contrasts with the background, so white type on
        a dark banner stays white instead of being redrawn in black.
        """
        darkest: tuple[int, int, int] | None = None
        brightest: tuple[int, int, int] | None = None
        darkest_luma = 10**6
        brightest_luma = -1

        # Stepped in device pixels rather than in points, so the walk actually
        # lands on the pixels the glyphs are drawn from however small the type.
        step_x = self._pixel_step(rect.width)
        step_y = self._pixel_step(rect.height)
        y = rect.y0
        while y <= rect.y1:
            x = rect.x0
            while x <= rect.x1:
                pixel = self._pixel(x, y)
                if pixel is not None:
                    luma = (pixel[0] * 299 + pixel[1] * 587 + pixel[2] * 114) // 1000
                    if luma < darkest_luma:
                        darkest_luma, darkest = luma, pixel
                    if luma > brightest_luma:
                        brightest_luma, brightest = luma, pixel
                x += step_x
            y += step_y

        candidate = darkest if _luminance(background) > 0.5 else brightest
        if candidate is None:
            return BLACK
        return (candidate[0] / 255.0, candidate[1] / 255.0, candidate[2] / 255.0)

    # -- internals ---------------------------------------------------------

    def _pixel_step(self, span_in_points: float) -> float:
        """A step, in points, that walks one device pixel at a time until that
        would cost more than `_MAXIMUM_SAMPLES_PER_AXIS` samples."""
        pixels = max(span_in_points * self._scale, 1.0)
        stride = max(1.0, pixels / _MAXIMUM_SAMPLES_PER_AXIS)
        return stride / self._scale

    def _pixel(self, x: float, y: float) -> tuple[int, int, int] | None:
        column = round(x * self._scale)
        row = round(y * self._scale)
        if not (0 <= column < self._width and 0 <= row < self._height):
            return None
        offset = row * self._stride + column * self._components
        if offset + 2 >= len(self._samples):
            return None
        return (
            self._samples[offset],
            self._samples[offset + 1],
            self._samples[offset + 2],
        )


def _dominant(samples: Sequence[tuple[int, int, int]]) -> Colour:
    counts: dict[int, tuple[int, int, int, int]] = {}
    for red, green, blue in samples:
        # 16 levels per channel: tight enough to separate a tint from white,
        # loose enough to absorb JPEG noise in a scan.
        key = (red // 16) << 8 | (green // 16) << 4 | (blue // 16)
        count, sum_r, sum_g, sum_b = counts.get(key, (0, 0, 0, 0))
        counts[key] = (count + 1, sum_r + red, sum_g + green, sum_b + blue)

    if not counts:
        return WHITE
    count, sum_r, sum_g, sum_b = max(counts.values(), key=lambda entry: entry[0])
    return (sum_r / count / 255.0, sum_g / count / 255.0, sum_b / count / 255.0)


def _luminance(colour: Colour) -> float:
    return 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]
