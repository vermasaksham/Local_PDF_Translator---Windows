"""Draws the translated text back onto the page.

The strategy is to edit the original document in place rather than to rebuild
it. Each translated block's original text is removed with a redaction — which
deletes the text objects themselves, so the output's text layer really is the
translation — and the translation is then set into the same rectangle. Images,
vector art, table rules, annotations, page boxes and rotation are never touched,
so everything the page contains other than the words it says survives exactly.

Fitting follows a shrink-then-reflow rule. German runs 15-30% longer than
English and Hindi longer still, so the type is scaled down first, within a
floor; if the translation still will not fit, it is set at the floor size and
allowed to run on into the whitespace below rather than being clipped. Losing a
paragraph silently would be far worse than a tight one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from ..core.languages import Language
from .colour import PageColourSampler
from .layout import PageLayout, Rect, TextBlock
from .textpainter import TextPainter, painter_for, rgb_from_int

# PyMuPDF spells these as module constants; resolved defensively so a version
# bump that renames one degrades to a sensible default instead of crashing.
_REDACT_IMAGE_NONE = getattr(pymupdf, "PDF_REDACT_IMAGE_NONE", 0)
_REDACT_IMAGE_PIXELS = getattr(pymupdf, "PDF_REDACT_IMAGE_PIXELS", 2)
_REDACT_LINE_ART_NONE = getattr(pymupdf, "PDF_REDACT_LINE_ART_NONE", 0)
_REDACT_TEXT_REMOVE = getattr(pymupdf, "PDF_REDACT_TEXT_REMOVE", 0)


@dataclass
class RenderOptions:
    """How hard the renderer may work to make a translation fit."""

    #: How far a block may be shrunk before it is allowed to overflow instead.
    minimum_scale: float = 0.62
    #: Never render below this point size; smaller is unreadable in print.
    minimum_point_size: float = 5.0
    #: Fraction of the starting size to step down by on each attempt.
    size_step: float = 0.04
    #: How far a block may grow downwards into whitespace, as a multiple of its
    #: original height.
    maximum_growth: float = 2.2
    #: Gap left between a block that has grown sideways and whatever it grew
    #: towards, so the two never touch.
    horizontal_clearance: float = 6.0
    #: Grown very slightly so a redaction covers the whole of the original
    #: glyphs including their antialiased edges.
    redaction_padding: float = 0.3
    #: OCR word boxes hug the ink more tightly than a PDF's own glyph boxes,
    #: and a scan's edges are soft, so scanned pages need a wider margin to
    #: avoid leaving a fringe of the original text showing.
    scanned_redaction_padding: float = 2.0


@dataclass
class BlockFit:
    """The result of fitting one translation into one block."""

    lines: list[str]
    size: float
    leading: float
    height: float
    #: The width the text was actually wrapped to, which for a single-line
    #: block may be wider than the block's own rectangle.
    width: float
    #: True when even the floor size did not fit and the text will run on.
    overflowed: bool


@dataclass
class PageRenderResult:
    blocks_drawn: int = 0
    #: Blocks that had to run on past the space available to them.
    overflowed: int = 0


class TranslatedPdfRenderer:
    def __init__(self, options: RenderOptions | None = None) -> None:
        self.options = options or RenderOptions()

    # -- one page ----------------------------------------------------------

    def render_page(
        self,
        page: pymupdf.Page,
        layout: PageLayout,
        translations: Sequence[str],
        target_language: Language,
        painter: TextPainter | None = None,
    ) -> PageRenderResult:
        """Replace each block's text with its translation.

        The page is expected to have had its rotation neutralised by the caller
        (see `extractor.unrotated`), so extraction and drawing share one space.
        """
        painter = painter or painter_for(target_language)

        # Not strict: a caller that supplies fewer translations than there are
        # blocks gets the remaining blocks left exactly as they were, which is
        # a far better outcome than refusing to render the page at all.
        pairs = [
            (block, translation.strip())
            for block, translation in zip(layout.blocks, translations, strict=False)
            if translation and translation.strip()
        ]
        if not pairs:
            return PageRenderResult()

        # A page that came from OCR needs its colours read back off the raster,
        # because the "text" there is pixels and states nothing about itself. A
        # page with a real text layer declares the colour of every span, and
        # rendering it to a bitmap would be the most expensive thing here.
        scanned = layout.was_recognised
        sampler = PageColourSampler(page) if scanned else None

        # Colours must be sampled before anything is redacted, since redaction
        # is what removes the very pixels being sampled.
        prepared = [
            (block, translation, *self._colours(block, sampler)) for block, translation in pairs
        ]

        # Every redaction is registered first and applied in one pass. Applying
        # them one at a time would be far slower, and applying them after the
        # new text was drawn would delete the translation as well.
        padding = (
            self.options.scanned_redaction_padding
            if scanned
            else self.options.redaction_padding
        )
        for block, _, _, background in prepared:
            rect = block.rect.inset(padding, padding)
            annotation = pymupdf.Rect(*rect.as_tuple())
            if background is None:
                # Removing the text objects is enough; leaving the area unfilled
                # lets whatever was behind them — an image, a tint, a table
                # cell — show through untouched.
                page.add_redact_annot(annotation)
            else:
                page.add_redact_annot(annotation, fill=background)
        page.apply_redactions(
            # On a scan the original words are part of the image, so the only
            # way to take them off the page is to clear the pixels underneath.
            # On an ordinary page that would punch holes in the artwork.
            images=_REDACT_IMAGE_PIXELS if scanned else _REDACT_IMAGE_NONE,
            graphics=_REDACT_LINE_ART_NONE,
            text=_REDACT_TEXT_REMOVE,
        )

        result = PageRenderResult(blocks_drawn=len(pairs))
        for block, translation, colour, _ in prepared:
            fit = self.fit(
                painter,
                translation,
                block,
                self.available_height(block, layout),
                self.available_width(block, layout),
            )
            if fit.overflowed:
                result.overflowed += 1
            # The text is set into a rectangle as wide as it was wrapped to,
            # which for a grown single-line block is wider than the block's
            # own box. The shaped painter sizes its image from this, so
            # passing the original box would clip Devanagari output.
            drawn = Rect(
                block.rect.x0,
                block.rect.y0,
                block.rect.x0 + fit.width,
                block.rect.y1,
            )
            painter.paint(
                page,
                fit.lines,
                drawn,
                fit.size,
                fit.leading,
                block.alignment,
                colour,
                bold=block.bold,
            )
        return result

    # -- fitting -----------------------------------------------------------

    def fit(
        self,
        painter: TextPainter,
        text: str,
        block: TextBlock,
        available_height: float,
        available_width: float | None = None,
    ) -> BlockFit:
        """Find the largest size at which `text` fits `block`.

        Steps down in small increments rather than binary searching: the step
        count is tiny, and a linear walk always lands on the largest size that
        fits instead of the largest the search happened to probe.
        """
        start_size = max(block.representative_font_size, 1.0)
        floor_size = max(
            start_size * self.options.minimum_scale, self.options.minimum_point_size
        )
        floor_size = min(floor_size, start_size)
        width = max(available_width if available_width is not None else block.rect.width, 1.0)
        step = max(start_size * self.options.size_step, 0.25)

        size = start_size
        while size >= floor_size:
            lines = painter.wrap(text, size, width, block.bold)
            leading = self._leading(block, size, start_size)
            height = painter.measure_height(lines, size, leading, block.bold)
            if height <= available_height:
                return BlockFit(lines, size, leading, height, width, overflowed=False)
            size -= step

        # Nothing fits even at the floor. Set it at the floor and let it run on
        # rather than dropping text.
        lines = painter.wrap(text, floor_size, width, block.bold)
        leading = self._leading(block, floor_size, start_size)
        height = painter.measure_height(lines, floor_size, leading, block.bold)
        return BlockFit(lines, floor_size, leading, height, width, overflowed=True)

    def _leading(self, block: TextBlock, size: float, start_size: float) -> float:
        """Keep the original leading ratio when the type is shrunk, so a
        tightly set block stays tight and an airy one stays airy."""
        scaled = block.line_height * (size / max(start_size, 0.01))
        return max(scaled, size * 1.05)

    def available_width(self, block: TextBlock, layout: PageLayout) -> float:
        """How wide a block may be set before it would collide with whatever
        is beside it.

        A block of several lines occupies a real column, and its width means
        something: wrapping the translation to it is right. A block of one line
        has no column — its width is simply how long the original words
        happened to be. Wrapping to that is what splits a table cell reading
        "East" across two lines the moment the replacement font is a hair wider
        than the original, so a single-line block is instead allowed to run
        rightwards into whatever space is actually free.
        """
        if len(block.lines) > 1:
            return max(block.rect.width, 1.0)

        # Blocks that sit beside this one, overlapping it vertically.
        beside = [
            other.rect.x0
            for other in layout.blocks
            if other is not block
            and other.rect.x0 >= block.rect.x1
            and other.rect.y1 > block.rect.y0
            and other.rect.y0 < block.rect.y1
        ]
        edge = min(beside) if beside else layout.rect.x1
        room = edge - block.rect.x0 - self.options.horizontal_clearance
        return max(block.rect.width, room, 1.0)

    def available_height(self, block: TextBlock, layout: PageLayout) -> float:
        """How tall a block may grow before it would collide with whatever is
        below it.

        Blocks are allowed to expand downwards into empty space, which absorbs
        most of a translation's extra length without shrinking the type at all.
        """
        # Only blocks that actually sit underneath this one, horizontally
        # overlapping it.
        below = [
            other.rect.y0
            for other in layout.blocks
            if other is not block
            and other.rect.y0 >= block.rect.y1
            and other.rect.x1 > block.rect.x0
            and other.rect.x0 < block.rect.x1
        ]
        ceiling = min(below) if below else layout.rect.y1
        room = ceiling - block.rect.y0 - block.line_height * 0.25
        return max(
            block.rect.height,
            min(room, block.rect.height * self.options.maximum_growth),
        )

    # -- colour ------------------------------------------------------------

    def _colours(
        self, block: TextBlock, sampler: PageColourSampler | None
    ) -> tuple[tuple[float, float, float], tuple[float, float, float] | None]:
        """The block's ink colour, and the background to paint over it with.

        A background of None means "leave the area alone", which is the right
        answer whenever the original text was a text object: removing it
        reveals whatever was behind it, exactly as it was.
        """
        if sampler is None:
            # The PDF told us exactly what colour this text was.
            return rgb_from_int(block.color), None
        background = sampler.background_around(block.rect)
        return sampler.ink_inside(block.rect, background), background


def block_rect(block: TextBlock) -> Rect:
    """Re-exported so callers need not reach into the layout module."""
    return block.rect
