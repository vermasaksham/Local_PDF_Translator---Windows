"""Turns loose glyph boxes into lines and paragraphs.

Deliberately free of PyMuPDF and Tesseract so the geometry heuristics — which
is where layout preservation actually lives or dies — can be unit tested on
synthetic input.

**Everything here preserves the input's logical order.** Sorting glyphs by
x-position would be simpler, but it reorders Devanagari matras (which are drawn
to the left of the consonant they follow logically) and it interleaves the
columns of a two-column page. PDF content streams are already stored in reading
order, so document order is both safer and cheaper.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise
from statistics import median

from .layout import Glyph, Rect, TextBlock, TextLine, union_of


class Ratio:
    """Tuning constants, expressed as multiples of the median glyph height so
    they hold at any point size."""

    #: Vertical tolerance for two glyphs to count as the same line.
    SAME_LINE = 0.5
    #: Horizontal gap that implies a word space.
    WORD_SPACE = 0.28
    #: Horizontal gap that implies a column break rather than a wide space.
    COLUMN_BREAK = 2.5
    #: Vertical gap between lines that still counts as the same paragraph.
    SAME_PARAGRAPH = 0.85
    #: Tolerance for edges to be considered aligned.
    EDGE_TOLERANCE = 0.6
    #: Largest font-size ratio two lines may differ by and still share a block.
    SIZE_JUMP = 1.35
    #: Fraction of the narrower line that must overlap horizontally.
    MINIMUM_OVERLAP = 0.4


def lines_from_glyphs(glyphs: Sequence[Glyph]) -> list[TextLine]:
    """Group glyphs, given in document order, into text lines."""
    usable = [glyph for glyph in glyphs if glyph.rect.is_finite and glyph.rect.height > 0]
    if not usable:
        return []

    heights = [glyph.rect.height for glyph in usable if glyph.rect.height > 0]
    unit = float(median(heights)) if heights else 10.0

    lines: list[TextLine] = []
    current: list[Glyph] = []
    current_centre = 0.0
    # The rightmost edge reached so far on this line. Gaps are measured against
    # this rather than against the previous glyph, because a combining mark
    # sits on top of its base and would otherwise leave the previous edge far
    # to the left, faking a word or column break.
    current_max_x = 0.0
    visible = 0

    def flush() -> None:
        nonlocal current, visible
        if current:
            line = _make_line(current, unit)
            if line is not None:
                lines.append(line)
        current = []
        visible = 0

    for glyph in usable:
        # Whitespace never starts a line and carries no useful box; spaces are
        # re-derived from the gaps between glyphs instead.
        if glyph.is_whitespace:
            if current:
                current.append(glyph)
            continue

        if visible == 0:
            current.append(glyph)
            current_centre = glyph.rect.mid_y
            current_max_x = glyph.rect.x1
            visible = 1
            continue

        changed_row = abs(glyph.rect.mid_y - current_centre) > unit * Ratio.SAME_LINE
        jumped_column = glyph.rect.x0 - current_max_x > unit * Ratio.COLUMN_BREAK

        if changed_row or jumped_column:
            flush()
            current.append(glyph)
            current_centre = glyph.rect.mid_y
            current_max_x = glyph.rect.x1
            visible = 1
        else:
            current.append(glyph)
            visible += 1
            # A running mean keeps a gently sloping line (a scan, or an italic
            # run) from drifting out of its own tolerance band.
            current_centre += (glyph.rect.mid_y - current_centre) / visible
            current_max_x = max(current_max_x, glyph.rect.x1)

    flush()
    return lines


def blocks_from_lines(lines: Sequence[TextLine]) -> list[TextBlock]:
    """Group lines, given in reading order, into paragraph-like blocks."""
    if not lines:
        return []

    groups: list[list[TextLine]] = []
    current: list[TextLine] = []

    for line in lines:
        if current and not _same_block(current[-1], line, current):
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)

    return [
        TextBlock(
            lines=group,
            rect=union_of([line.rect for line in group]),
            alignment=_alignment(group),
        )
        for group in groups
    ]


# --------------------------------------------------------------------------
# Line assembly


def _make_line(glyphs: Sequence[Glyph], unit: float) -> TextLine | None:
    # Leading and trailing whitespace glyphs contribute nothing but would
    # inflate the frame.
    trimmed = list(glyphs)
    while trimmed and trimmed[0].is_whitespace:
        trimmed.pop(0)
    while trimmed and trimmed[-1].is_whitespace:
        trimmed.pop()
    if not trimmed:
        return None

    text = ""
    max_x: float | None = None
    for glyph in trimmed:
        if glyph.is_whitespace:
            if text and not text.endswith(" "):
                text += " "
            continue
        # As in `lines_from_glyphs`, the gap is measured from the rightmost
        # edge reached so far, so a combining mark drawn over its base does not
        # look like a word break to the glyph that follows it.
        if (
            max_x is not None
            and glyph.rect.x0 - max_x > unit * Ratio.WORD_SPACE
            and not text.endswith(" ")
        ):
            text += " "
        text += glyph.text
        max_x = glyph.rect.x1 if max_x is None else max(max_x, glyph.rect.x1)

    text = text.strip()
    if not text:
        return None

    visible = [glyph for glyph in trimmed if not glyph.is_whitespace]
    rect = union_of([glyph.rect for glyph in visible])

    # Prefer the size the PDF itself declares. Only when it is absent (OCR, or
    # a malformed file) fall back to the glyph box, which spans ascender to
    # descender and so overestimates the point size slightly; 0.92 lands close
    # for the common text faces.
    declared = [glyph.size for glyph in visible if glyph.size > 0]
    if declared:
        size = float(median(declared))
    else:
        boxes = [glyph.rect.height for glyph in visible]
        size = (float(median(boxes)) if boxes else rect.height) * 0.92

    return TextLine(
        text=text,
        rect=rect,
        font_size=max(size, 1.0),
        color=_dominant_colour(visible),
        bold=_majority(visible, lambda glyph: glyph.bold),
        italic=_majority(visible, lambda glyph: glyph.italic),
    )


def _dominant_colour(glyphs: Sequence[Glyph]) -> int:
    counts: dict[int, int] = {}
    for glyph in glyphs:
        counts[glyph.color] = counts.get(glyph.color, 0) + 1
    if not counts:
        return 0
    return max(counts.items(), key=lambda item: item[1])[0]


def _majority(glyphs: Sequence[Glyph], predicate) -> bool:
    if not glyphs:
        return False
    return sum(1 for glyph in glyphs if predicate(glyph)) / len(glyphs) > 0.6


# --------------------------------------------------------------------------
# Block assembly


# A line opening with one of these is a new item in a list, not the
# continuation of the previous one. Merging a list into a single paragraph
# translates fine but redraws as one run-on block, losing the list entirely.
_LIST_MARKER = re.compile(
    r"""^(
        [\u2022\u00b7\u2023\u25aa\u25e6\u2043\u2219*]   # bullet glyphs
      | [-\u2013\u2014]\s                                    # dash followed by a space
      | \(?\d{1,2}[.)]\s                                     # 1.  1)  (1)
      | \(?[a-z][.)]\s                                        # a.  a)  (a)
      | \(?[ivx]{1,4}[.)]\s                                   # i.  iv)
    )""",
    re.VERBOSE,
)


def starts_a_list_item(text: str) -> bool:
    """Whether a line opens a new item in a bulleted or numbered list."""
    return bool(_LIST_MARKER.match(text.strip()))


def _same_block(previous: TextLine, nxt: TextLine, block: Sequence[TextLine]) -> bool:
    # Each list item is its own block, so the list survives being redrawn.
    # A wrapped continuation line carries no marker and stays where it is.
    if starts_a_list_item(nxt.text):
        return False

    # A heading and its body text must not merge, or the heading's size is lost
    # when the block is redrawn at a single size.
    smaller = max(min(previous.font_size, nxt.font_size), 0.01)
    if max(previous.font_size, nxt.font_size) / smaller >= Ratio.SIZE_JUMP:
        return False

    # Weight is the other half of that signal, and it catches the case size
    # alone misses: a bold 12pt heading over 9.5pt body text is only a 1.26x
    # jump, under the size threshold, but it is plainly not one paragraph.
    if previous.bold != nxt.bold:
        return False

    # Vertical adjacency, measured against the leading the block has already
    # established rather than the font size alone. A negative gap means the
    # next line sits above the previous one — a column or page-region jump.
    established = _established_line_height(block) or previous.font_size * 1.2
    gap = nxt.rect.y0 - previous.rect.y1
    if not (-previous.rect.height < gap < established * Ratio.SAME_PARAGRAPH):
        return False

    # Horizontal overlap keeps side-by-side columns apart even when their lines
    # happen to be adjacent in the content stream.
    overlap = min(previous.rect.x1, nxt.rect.x1) - max(previous.rect.x0, nxt.rect.x0)
    narrower = min(previous.rect.width, nxt.rect.width)
    return narrower > 0 and overlap / narrower > Ratio.MINIMUM_OVERLAP


def _established_line_height(block: Sequence[TextLine]) -> float | None:
    if len(block) < 2:
        return None
    tops = [line.rect.y0 for line in block]
    gaps = [b - a for a, b in pairwise(tops) if b - a > 0]
    return float(median(gaps)) if gaps else None


def _alignment(lines: Sequence[TextLine]) -> str:
    if len(lines) < 2:
        return "left"
    sizes = [line.font_size for line in lines]
    tolerance = float(median(sizes)) * Ratio.EDGE_TOLERANCE

    # The last line of a justified paragraph is short by design, so it is
    # excluded when judging the right edge — but only once there are enough
    # lines left to say anything. Dropping the last of two leaves a single
    # value, whose spread is trivially zero, and every two-line block would
    # then be reported as right-aligned.
    right_edges = [line.rect.x1 for line in lines]
    if len(lines) >= 3:
        right_edges = right_edges[:-1]

    left_spread = _spread([line.rect.x0 for line in lines])
    right_spread = _spread(right_edges)
    centre_spread = _spread([line.rect.mid_x for line in lines])

    if left_spread <= tolerance:
        return "left"
    if centre_spread <= tolerance and centre_spread < right_spread:
        return "centre"
    if right_spread <= tolerance:
        return "right"
    return "left"


def _spread(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return max(values) - min(values)


def bounding_rect(rects: Sequence[Rect]) -> Rect:
    """Re-exported for callers that only import this module."""
    return union_of(rects)
