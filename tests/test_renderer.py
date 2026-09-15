"""Shrink-then-reflow fitting, measured against a painter with known metrics."""

from __future__ import annotations

import pytest

from local_pdf_translator.pdf.layout import PageLayout, Rect, TextBlock, TextLine
from local_pdf_translator.pdf.renderer import RenderOptions, TranslatedPdfRenderer
from local_pdf_translator.pdf.textpainter import LineMetrics, TextPainter


class RulerPainter(TextPainter):
    """A painter where every character is exactly `size` wide and one line is
    exactly `size` tall, so expected results can be worked out by hand."""

    def __init__(self, advance: float = 1.0) -> None:
        self.advance = advance
        self.painted: list[tuple[list[str], float]] = []

    def text_width(self, text, size, bold=False):
        return len(text) * size * self.advance

    def metrics(self, size, bold=False):
        return LineMetrics(ascender=size * 0.8, descender=size * 0.2)

    def paint(self, page, lines, rect, size, leading, alignment, colour, bold=False):
        self.painted.append((list(lines), size))


def block(text="word " * 10, x0=0.0, y0=0.0, width=100.0, height=24.0, size=10.0):
    """A two-line block of the given geometry."""
    half = height / 2
    lines = [
        TextLine(text, Rect(x0, y0, x0 + width, y0 + half), size),
        TextLine(text, Rect(x0, y0 + half, x0 + width, y0 + height), size),
    ]
    return TextBlock(lines=lines, rect=Rect(x0, y0, x0 + width, y0 + height))


@pytest.fixture
def renderer():
    return TranslatedPdfRenderer()


@pytest.fixture
def painter():
    return RulerPainter()


# -- wrapping --------------------------------------------------------------


def test_text_wraps_to_the_box_width(painter):
    # Every character is 1pt wide at size 1, so 10 characters fit in 10pt.
    lines = painter.wrap("aaaa bbbb cccc dddd", size=1.0, max_width=10.0)
    assert lines == ["aaaa bbbb", "cccc dddd"]


def test_a_word_wider_than_the_box_is_split_rather_than_overhanging(painter):
    lines = painter.wrap("aaaaaaaaaaaaaaa", size=1.0, max_width=5.0)
    assert lines == ["aaaaa", "aaaaa", "aaaaa"]
    assert "".join(lines) == "aaaaaaaaaaaaaaa"


def test_wrapping_never_loses_a_word(painter):
    text = " ".join(f"word{index}" for index in range(40))
    lines = painter.wrap(text, size=1.0, max_width=30.0)
    assert " ".join(lines).split() == text.split()


def test_explicit_newlines_are_kept(painter):
    assert painter.wrap("one\ntwo", size=1.0, max_width=100.0) == ["one", "two"]


# -- fitting ---------------------------------------------------------------


def test_text_that_already_fits_keeps_its_original_size(renderer, painter):
    target = block(size=10.0, width=100.0, height=24.0)
    fit = renderer.fit(painter, "short", target, available_height=24.0)
    assert fit.size == 10.0
    assert not fit.overflowed


def test_longer_text_is_shrunk_to_fit(renderer, painter):
    target = block(size=10.0, width=100.0, height=24.0)
    # 36 characters needs four lines at 10pt (too tall for a 24pt box) but
    # only three once the type comes down a little — the ordinary German case.
    fit = renderer.fit(painter, "x " * 18, target, available_height=24.0)
    assert fit.size < 10.0
    assert not fit.overflowed
    assert fit.height <= 24.0


def test_shrinking_stops_at_the_floor_and_the_text_then_runs_on(renderer, painter):
    options = RenderOptions(minimum_scale=0.6, minimum_point_size=1.0)
    renderer = TranslatedPdfRenderer(options)
    target = block(size=10.0, width=100.0, height=24.0)

    fit = renderer.fit(painter, "x " * 4000, target, available_height=24.0)
    # It never goes below the floor...
    assert fit.size == pytest.approx(6.0)
    # ...and it reports that it had to overflow rather than silently clipping.
    assert fit.overflowed
    # Nothing is dropped: every piece of the text is still present.
    assert "".join(fit.lines).count("x") == 4000


def test_the_minimum_point_size_is_respected_for_tiny_type(renderer, painter):
    options = RenderOptions(minimum_scale=0.1, minimum_point_size=5.0)
    renderer = TranslatedPdfRenderer(options)
    target = block(size=6.0, width=100.0, height=12.0)
    fit = renderer.fit(painter, "x " * 2000, target, available_height=12.0)
    assert fit.size >= 5.0


def test_leading_shrinks_with_the_type(renderer, painter):
    target = block(size=10.0, width=100.0, height=24.0)
    roomy = renderer.fit(painter, "short", target, available_height=24.0)
    tight = renderer.fit(painter, "x " * 60, target, available_height=24.0)
    assert tight.leading < roomy.leading


def test_leading_never_collapses_below_the_type_size(renderer, painter):
    target = block(size=10.0, width=100.0, height=24.0)
    fit = renderer.fit(painter, "x " * 60, target, available_height=24.0)
    assert fit.leading >= fit.size


# -- available height ------------------------------------------------------


def test_a_block_may_grow_into_the_whitespace_below_it(renderer):
    target = block(y0=100.0, height=24.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [target])
    # Nothing is underneath, so it may use its allowance in full.
    assert renderer.available_height(target, layout) > target.rect.height


def test_a_block_may_not_grow_into_the_one_below_it(renderer):
    upper = block(y0=100.0, height=24.0)
    lower = block(y0=130.0, height=24.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [upper, lower])
    available = renderer.available_height(upper, layout)
    # It may reach down towards the next block but must not reach past it.
    assert available <= lower.rect.y0 - upper.rect.y0


def test_growth_is_capped_even_on_an_empty_page(renderer):
    target = block(y0=100.0, height=24.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [target])
    options = RenderOptions()
    assert renderer.available_height(target, layout) <= (
        target.rect.height * options.maximum_growth
    )


def test_a_block_beside_another_is_not_blocked_by_it(renderer):
    # Side by side, not stacked: the right-hand block must not limit the left.
    left = block(x0=0.0, y0=100.0, width=200.0, height=24.0)
    right = block(x0=300.0, y0=130.0, width=200.0, height=24.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [left, right])
    assert renderer.available_height(left, layout) > left.rect.height


# -- available width -------------------------------------------------------


def single_line_block(text="East", x0=76.0, y0=100.0, width=20.0, size=10.0):
    rect = Rect(x0, y0, x0 + width, y0 + 12.0)
    return TextBlock(lines=[TextLine(text, rect, size)], rect=rect)


def test_a_single_line_block_may_grow_sideways(renderer):
    # Its width is just how long the original word was, not a column.
    target = single_line_block()
    layout = PageLayout(0, Rect(0, 0, 595, 842), [target])
    assert renderer.available_width(target, layout) > target.rect.width * 5


def test_a_single_line_block_stops_at_its_neighbour(renderer):
    cell = single_line_block(x0=76.0, width=20.0)
    neighbour = single_line_block(x0=254.0, width=25.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [cell, neighbour])
    available = renderer.available_width(cell, layout)
    assert available <= neighbour.rect.x0 - cell.rect.x0
    assert available > cell.rect.width


def test_a_block_above_another_does_not_limit_its_width(renderer):
    cell = single_line_block(x0=76.0, y0=100.0)
    elsewhere = single_line_block(x0=254.0, y0=400.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [cell, elsewhere])
    # They do not overlap vertically, so the far block is no obstacle.
    assert renderer.available_width(cell, layout) > 400


def test_a_multi_line_block_keeps_its_column_width(renderer):
    # A real paragraph: its width means something and must be respected.
    paragraph = block(width=200.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [paragraph])
    assert renderer.available_width(paragraph, layout) == paragraph.rect.width


def test_a_short_label_is_not_split_across_lines(renderer, painter):
    """The bug this guards against turned a table cell reading "East" into
    "Eas" and "t" whenever the replacement font was a shade wider."""
    cell = single_line_block(text="East", width=20.0)
    layout = PageLayout(0, Rect(0, 0, 595, 842), [cell])
    fit = renderer.fit(
        painter,
        "Osten",
        cell,
        renderer.available_height(cell, layout),
        renderer.available_width(cell, layout),
    )
    assert fit.lines == ["Osten"]
    assert fit.size == cell.representative_font_size
