"""Layout heuristics, exercised on synthetic glyph boxes.

Layout preservation lives or dies here, and these are the cases that decide
whether a two-column page comes out as two columns or as interleaved nonsense.
"""

from __future__ import annotations

from local_pdf_translator.pdf.analyser import blocks_from_lines, lines_from_glyphs
from local_pdf_translator.pdf.layout import Glyph, Rect, TextLine


def glyph(text, x, y, width=6.0, height=10.0, size=10.0, **kwargs):
    """One character box. y is the top edge, as everywhere in the pdf package."""
    return Glyph(text=text, rect=Rect(x, y, x + width, y + height), size=size, **kwargs)


def run(text, x, y, advance=6.0, **kwargs):
    """A row of glyphs spelling `text`, laid out left to right."""
    return [glyph(char, x + index * advance, y, **kwargs) for index, char in enumerate(text)]


def line(text, x0, y0, x1, y1, size=10.0, **kwargs):
    return TextLine(text=text, rect=Rect(x0, y0, x1, y1), font_size=size, **kwargs)


# -- lines -----------------------------------------------------------------


def test_glyphs_on_one_row_become_one_line():
    result = lines_from_glyphs(run("HELLO", 10, 100))
    assert [item.text for item in result] == ["HELLO"]


def test_a_new_row_starts_a_new_line():
    glyphs = run("ONE", 10, 100) + run("TWO", 10, 120)
    assert [item.text for item in lines_from_glyphs(glyphs)] == ["ONE", "TWO"]


def test_a_wide_horizontal_gap_is_read_as_a_column_break():
    # Same row, but the second run starts far to the right: two columns whose
    # lines happen to be adjacent in the content stream.
    glyphs = run("LEFT", 10, 100) + run("RIGHT", 300, 100)
    assert [item.text for item in lines_from_glyphs(glyphs)] == ["LEFT", "RIGHT"]


def test_a_small_gap_becomes_a_word_space():
    glyphs = run("ONE", 10, 100) + run("TWO", 34, 100)
    assert [item.text for item in lines_from_glyphs(glyphs)] == ["ONE TWO"]


def test_explicit_space_characters_are_honoured():
    result = lines_from_glyphs(run("A B", 10, 100))
    assert [item.text for item in result] == ["A B"]


def test_whitespace_never_starts_or_ends_a_line():
    glyphs = [glyph(" ", 4, 100)] + run("WORD", 10, 100) + [glyph(" ", 40, 100)]
    result = lines_from_glyphs(glyphs)
    assert [item.text for item in result] == ["WORD"]
    # The frame must not be inflated by the stripped spaces.
    assert result[0].rect.x0 == 10


def test_degenerate_boxes_are_ignored():
    glyphs = run("OK", 10, 100) + [Glyph("x", Rect(0, 0, 0, 0))]
    assert [item.text for item in lines_from_glyphs(glyphs)] == ["OK"]


def test_declared_font_size_beats_the_glyph_box():
    # The box is 10pt tall but the PDF says the type is 24pt; believe the PDF.
    result = lines_from_glyphs(run("BIG", 10, 100, size=24.0))
    assert result[0].font_size == 24.0


def test_font_size_falls_back_to_the_box_when_undeclared():
    result = lines_from_glyphs(run("X", 10, 100, height=20.0, size=0.0))
    assert 17.0 < result[0].font_size < 19.0


def test_empty_input_produces_no_lines():
    assert lines_from_glyphs([]) == []


# -- blocks ----------------------------------------------------------------


def test_adjacent_lines_of_one_size_form_a_paragraph():
    lines = [
        line("first line of the text", 72, 100, 300, 112),
        line("second line of the text", 72, 113, 300, 125),
        line("third line of the text", 72, 126, 300, 138),
    ]
    blocks = blocks_from_lines(lines)
    assert len(blocks) == 1
    assert blocks[0].joined_text == (
        "first line of the text second line of the text third line of the text"
    )


def test_a_large_heading_does_not_merge_with_its_body():
    lines = [
        line("Heading", 72, 100, 200, 122, size=22.0),
        line("body text follows", 72, 126, 300, 138, size=10.0),
    ]
    assert len(blocks_from_lines(lines)) == 2


def test_a_bold_heading_splits_even_at_a_similar_size():
    # 12pt over 9.5pt is only a 1.26x jump — under the size threshold. Weight
    # is what separates them.
    lines = [
        line("Notes to the accounts", 72, 100, 200, 112, size=12.0, bold=True),
        line("all figures are unaudited", 72, 114, 300, 124, size=9.5, bold=False),
    ]
    assert len(blocks_from_lines(lines)) == 2


def test_a_big_vertical_gap_starts_a_new_block():
    lines = [
        line("end of one paragraph", 72, 100, 300, 112),
        line("start of another", 72, 200, 300, 212),
    ]
    assert len(blocks_from_lines(lines)) == 2


def test_side_by_side_columns_stay_apart():
    # Interleaved in the stream, as a two-column content stream often is.
    lines = [
        line("left column line one", 72, 100, 280, 112),
        line("right column line one", 320, 100, 520, 112),
        line("left column line two", 72, 113, 280, 125),
        line("right column line two", 320, 113, 520, 125),
    ]
    blocks = blocks_from_lines(lines)
    assert len(blocks) == 4 or all(
        # Whatever the grouping, no block may span both columns.
        block.rect.width < 300
        for block in blocks
    )


def test_a_line_above_the_previous_one_starts_a_new_block():
    lines = [
        line("bottom of the first column", 72, 700, 280, 712),
        line("top of the second column", 320, 100, 520, 112),
    ]
    assert len(blocks_from_lines(lines)) == 2


# -- text repair -----------------------------------------------------------


def test_hyphenated_words_are_rejoined_across_the_line_break():
    lines = [
        line("the inter-", 72, 100, 200, 112),
        line("national agreement", 72, 113, 250, 125),
    ]
    assert blocks_from_lines(lines)[0].joined_text == "the international agreement"


def test_an_em_dash_at_the_end_of_a_line_is_not_a_hyphenation():
    lines = [
        line("the result--", 72, 100, 200, 112),
        line("and its cause", 72, 113, 250, 125),
    ]
    assert blocks_from_lines(lines)[0].joined_text == "the result-- and its cause"


# -- alignment -------------------------------------------------------------


def test_a_flush_left_paragraph_is_detected():
    lines = [
        line("aaaa aaaa aaaa", 72, 100, 300, 112),
        line("bbbb bbbb", 72, 113, 250, 125),
    ]
    assert blocks_from_lines(lines)[0].alignment == "left"


def test_a_centred_paragraph_is_detected():
    lines = [
        line("a longer centred line", 100, 100, 300, 112),
        line("shorter one", 150, 113, 250, 125),
    ]
    assert blocks_from_lines(lines)[0].alignment == "centre"


def test_a_right_aligned_paragraph_is_detected():
    lines = [
        line("a longer right aligned line", 100, 100, 300, 112),
        line("shorter", 220, 113, 300, 125),
    ]
    assert blocks_from_lines(lines)[0].alignment == "right"


# -- derived properties ----------------------------------------------------


def test_representative_size_ignores_a_stray_footnote_marker():
    lines = [
        line("body", 72, 100, 200, 112, size=10.0),
        line("body", 72, 113, 200, 125, size=10.0),
        line("1", 72, 126, 80, 132, size=6.0),
    ]
    assert blocks_from_lines(lines)[0].representative_font_size == 10.0


def test_line_height_is_the_median_baseline_gap():
    lines = [
        line("one", 72, 100, 200, 112),
        line("two", 72, 114, 200, 126),
        line("three", 72, 128, 200, 140),
    ]
    assert blocks_from_lines(lines)[0].line_height == 14.0


def test_block_colour_is_the_colour_of_most_of_its_text():
    lines = [
        line("a long white heading", 72, 100, 300, 112, color=0xFFFFFF),
        line("short", 72, 113, 120, 125, color=0x000000),
    ]
    assert blocks_from_lines(lines)[0].color == 0xFFFFFF
