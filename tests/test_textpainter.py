"""Text drawing, including the Devanagari shaping path.

Hindi is the reason this module has two backends: PDF text drawing emits code
points in logical order with no shaping, so `कि` would come out with its vowel
sign on the wrong side of the consonant. These tests check that the shaped path
is selected, that it is actually available, and that it puts ink on the page.
"""

from __future__ import annotations

import pymupdf
import pytest

from local_pdf_translator.core import languages
from local_pdf_translator.pdf import fonts
from local_pdf_translator.pdf.layout import Rect
from local_pdf_translator.pdf.textpainter import (
    ShapedTextPainter,
    VectorTextPainter,
    painter_for,
    rgb_from_int,
    shaping_status,
)

HINDI_TEXT = "तिमाही रिपोर्ट में वृद्धि दर्ज की गई है।"


def has_font(language) -> bool:
    try:
        fonts.font_for(language)
    except fonts.FontNotFound:
        return False
    return True


needs_devanagari = pytest.mark.skipif(
    not has_font(languages.HINDI), reason="no Devanagari font on this machine"
)


@pytest.fixture
def page():
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    yield page
    document.close()


def ink_fraction(page) -> float:
    """The proportion of the page that is not white — i.e. how much was drawn."""
    pixmap = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY, alpha=False)
    samples = pixmap.samples
    dark = sum(1 for value in samples if value < 200)
    return dark / max(len(samples), 1)


# -- backend selection -----------------------------------------------------


def test_latin_languages_use_the_vector_backend():
    # Real, selectable, searchable text — the good path.
    assert isinstance(painter_for(languages.ENGLISH), VectorTextPainter)
    assert isinstance(painter_for(languages.GERMAN), VectorTextPainter)


@needs_devanagari
def test_hindi_uses_the_shaped_backend():
    assert isinstance(painter_for(languages.HINDI), ShapedTextPainter)


def test_only_devanagari_is_declared_as_needing_shaping():
    assert languages.HINDI.script.needs_shaping
    assert not languages.ENGLISH.script.needs_shaping


def test_shaping_is_available():
    """Complex scripts must really be shaped, or Hindi output is silently wrong.

    If this fails, the app still runs — it shows a banner saying so — but the
    Hindi output is not trustworthy.
    """
    working, reason = shaping_status()
    assert working, f"Devanagari is not being shaped: {reason}"


# -- colour ----------------------------------------------------------------


@pytest.mark.parametrize(
    "packed,expected",
    [
        (0x000000, (0.0, 0.0, 0.0)),
        (0xFFFFFF, (1.0, 1.0, 1.0)),
        (0xFF0000, (1.0, 0.0, 0.0)),
        (0x0000FF, (0.0, 0.0, 1.0)),
    ],
)
def test_span_colours_unpack_correctly(packed, expected):
    assert rgb_from_int(packed) == pytest.approx(expected)


# -- measurement -----------------------------------------------------------


def test_width_grows_with_the_text():
    painter = painter_for(languages.ENGLISH)
    assert painter.text_width("iiii", 12) < painter.text_width("mmmm", 12)


def test_width_scales_with_the_point_size():
    painter = painter_for(languages.ENGLISH)
    small = painter.text_width("Hamburgefonstiv", 10)
    large = painter.text_width("Hamburgefonstiv", 20)
    assert large == pytest.approx(small * 2, rel=0.02)


def test_an_empty_string_has_no_width():
    assert painter_for(languages.ENGLISH).text_width("", 12) == 0.0


@needs_devanagari
def test_devanagari_measurement_reflects_shaping():
    painter = painter_for(languages.HINDI)
    # A conjunct is narrower than its parts drawn separately would be; what
    # matters here is that measuring returns something sane and positive.
    assert painter.text_width(HINDI_TEXT, 12) > 0
    assert painter.text_width(HINDI_TEXT, 24) > painter.text_width(HINDI_TEXT, 12)


# -- drawing ---------------------------------------------------------------


def test_latin_text_is_drawn_as_real_text(page):
    painter = painter_for(languages.ENGLISH)
    rect = Rect(72, 72, 400, 200)
    painter.paint(page, ["Hamburgefonstiv"], rect, 14.0, 17.0, "left", (0, 0, 0))

    assert "Hamburgefonstiv" in page.get_text("text")
    assert page.search_for("Hamburgefonstiv")


@needs_devanagari
def test_devanagari_text_is_drawn_as_an_image(page):
    painter = painter_for(languages.HINDI)
    rect = Rect(72, 72, 400, 200)
    painter.paint(page, [HINDI_TEXT], rect, 14.0, 17.0, "left", (0, 0, 0))

    # Shaped output is a picture of text, which is the price of correctness.
    assert len(page.get_images()) == 1
    assert ink_fraction(page) > 0.0005, "nothing was actually drawn"


@needs_devanagari
def test_devanagari_is_not_drawn_as_empty_boxes(page):
    """A Latin font asked for Devanagari draws tofu.

    Tofu is uniform and blocky, so it covers noticeably more of the line than
    real shaped text does. This catches the case where the font resolver picked
    a face with no Devanagari coverage.
    """
    painter = painter_for(languages.HINDI)
    painter.paint(page, [HINDI_TEXT], Rect(72, 72, 500, 120), 20.0, 24.0, "left", (0, 0, 0))
    coverage = ink_fraction(page)
    assert 0.0005 < coverage < 0.02, f"suspicious ink coverage {coverage}"


def test_nothing_is_drawn_for_empty_input(page):
    painter = painter_for(languages.ENGLISH)
    painter.paint(page, [], Rect(72, 72, 400, 200), 14.0, 17.0, "left", (0, 0, 0))
    assert page.get_text("text").strip() == ""


def test_colour_is_honoured(page):
    painter = painter_for(languages.ENGLISH)
    painter.paint(page, ["Red text"], Rect(72, 72, 400, 100), 20.0, 24.0, "left", (1, 0, 0))
    layout_colour = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]["color"]
    assert layout_colour == 0xFF0000


@pytest.mark.parametrize("alignment", ["left", "centre", "right"])
def test_alignment_places_the_line_differently(page, alignment):
    painter = painter_for(languages.ENGLISH)
    rect = Rect(72, 72, 500, 120)
    painter.paint(page, ["short"], rect, 12.0, 14.0, alignment, (0, 0, 0))

    span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    left = span["bbox"][0]
    if alignment == "left":
        assert left == pytest.approx(72, abs=2)
    elif alignment == "right":
        assert span["bbox"][2] == pytest.approx(500, abs=2)
    else:
        assert 72 < left < 500


def test_wrapped_lines_are_stacked_by_the_leading(page):
    painter = painter_for(languages.ENGLISH)
    painter.paint(
        page, ["first", "second"], Rect(72, 72, 400, 200), 12.0, 20.0, "left", (0, 0, 0)
    )
    # Each line is its own text object, so PyMuPDF may report them in separate
    # blocks; what matters is where they sit, not how they are grouped.
    tops = sorted(
        line["bbox"][1]
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", ())
    )
    assert len(tops) == 2
    assert tops[1] - tops[0] == pytest.approx(20.0, abs=1.0)


# -- fonts -----------------------------------------------------------------


def test_a_latin_font_is_found():
    choice = fonts.font_for(languages.ENGLISH)
    assert choice.regular.exists()


@needs_devanagari
def test_the_devanagari_font_is_not_a_latin_one():
    latin = fonts.font_for(languages.ENGLISH)
    devanagari = fonts.font_for(languages.HINDI)
    assert devanagari.regular != latin.regular
