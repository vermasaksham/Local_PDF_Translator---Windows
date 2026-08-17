"""The geometry types the PDF pipeline passes around.

Everything here is in PyMuPDF's page coordinate space: the origin is the
top-left of the page and y increases *downwards*. That is the opposite of the
convention in the PDF file format itself, but it is what every PyMuPDF call
expects, and converting once at the edges is far less error-prone than
flipping coordinates in the middle of the layout heuristics.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle, y growing downwards."""

    x0: float
    y0: float  # top
    x1: float
    y1: float  # bottom

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def mid_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def mid_y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def is_finite(self) -> bool:
        """False for the NaN and infinite boxes damaged PDFs report.

        Worth checking explicitly: a single NaN box poisons the median glyph
        height, and every layout heuristic is expressed as a multiple of it.
        """
        return all(math.isfinite(value) for value in (self.x0, self.y0, self.x1, self.y1))

    def inset(self, dx: float, dy: float) -> Rect:
        """A rectangle grown by `dx`/`dy` on each side (negative shrinks it)."""
        return Rect(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def union(self, other: Rect) -> Rect:
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


def union_of(rects: Sequence[Rect]) -> Rect:
    if not rects:
        return Rect(0, 0, 0, 0)
    result = rects[0]
    for rect in rects[1:]:
        result = result.union(rect)
    return result


@dataclass(frozen=True)
class Glyph:
    """One character and the box it occupies.

    Holds a string rather than a single character because a Devanagari
    syllable such as कि arrives as a base consonant and a combining vowel with
    separate boxes, and they must be able to recombine into one grapheme when
    the line is assembled.
    """

    text: str
    rect: Rect
    #: Point size reported by the PDF itself, which beats guessing from the box.
    size: float = 0.0
    #: PostScript name of the original font, kept for weight detection.
    font: str = ""
    #: sRGB packed as 0xRRGGBB, as PyMuPDF reports span colours.
    color: int = 0
    #: PyMuPDF span flags; bit 4 is bold, bit 1 is italic.
    flags: int = 0

    @property
    def is_whitespace(self) -> bool:
        return not self.text.strip()

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16) or "bold" in self.font.lower()

    @property
    def italic(self) -> bool:
        return bool(self.flags & 2) or "italic" in self.font.lower()


@dataclass(frozen=True)
class TextLine:
    """A single laid-out line of text on a page."""

    text: str
    rect: Rect
    font_size: float
    color: int = 0
    bold: bool = False
    italic: bool = False


@dataclass
class TextBlock:
    """A run of lines that reads as one unit — a paragraph, a heading, a caption.

    Translation happens per block rather than per line: an NMT model given
    "the quick brown" and "fox jumps over" as separate inputs produces
    nonsense, whereas the joined sentence translates correctly and is then
    re-wrapped into the block's own rectangle.
    """

    lines: list[TextLine]
    rect: Rect
    alignment: str = "left"  # "left" | "centre" | "right"

    @property
    def joined_text(self) -> str:
        """The block's text with soft line breaks joined and hyphens repaired."""
        result = ""
        for index, line in enumerate(self.lines):
            piece = line.text.strip()
            if index == 0:
                result = piece
                continue
            # A line ending in a hyphen is almost always a word split across
            # the line break; rejoining it before translation matters a lot.
            if result.endswith("-") and not result.endswith("--"):
                result = result[:-1] + piece
            else:
                result += " " + piece
        return result

    @property
    def representative_font_size(self) -> float:
        """Median font size across the block's lines, which is more robust than
        the mean when a block picks up a stray superscript or footnote marker."""
        sizes = [line.font_size for line in self.lines if line.font_size > 0]
        return float(median(sizes)) if sizes else 11.0

    @property
    def line_height(self) -> float:
        """Typical distance between consecutive baselines, used to re-wrap the
        translation at the original leading."""
        if len(self.lines) < 2:
            first = self.lines[0].rect.height if self.lines else 0.0
            return first or self.representative_font_size * 1.2
        tops = sorted(line.rect.y0 for line in self.lines)
        gaps = [b - a for a, b in pairwise(tops) if b - a > 0]
        return float(median(gaps)) if gaps else self.representative_font_size * 1.2

    @property
    def color(self) -> int:
        """The colour most of the block's text is set in."""
        if not self.lines:
            return 0
        counts: dict[int, int] = {}
        for line in self.lines:
            counts[line.color] = counts.get(line.color, 0) + len(line.text)
        return max(counts.items(), key=lambda item: item[1])[0]

    @property
    def bold(self) -> bool:
        """True when most of the block is bold, so headings stay heavy."""
        if not self.lines:
            return False
        heavy = sum(len(line.text) for line in self.lines if line.bold)
        total = sum(len(line.text) for line in self.lines) or 1
        return heavy / total > 0.6

    @property
    def italic(self) -> bool:
        if not self.lines:
            return False
        slanted = sum(len(line.text) for line in self.lines if line.italic)
        total = sum(len(line.text) for line in self.lines) or 1
        return slanted / total > 0.6


@dataclass
class PageLayout:
    """Everything extracted from one page."""

    page_index: int
    rect: Rect
    blocks: list[TextBlock] = field(default_factory=list)
    #: True when the text came from OCR rather than an embedded text layer.
    was_recognised: bool = False
