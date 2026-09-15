"""Text recognition for scanned pages.

The parsing tests run everywhere; the ones that actually shell out to Tesseract
skip themselves when it is not installed, so a checkout without it still has a
green suite.
"""

from __future__ import annotations

import pymupdf
import pytest
from conftest import StubEngine

from local_pdf_translator.core import languages
from local_pdf_translator.pdf import extractor, ocr
from local_pdf_translator.pdf.pipeline import Options, PdfTranslationPipeline

needs_tesseract = pytest.mark.skipif(
    not ocr.availability().available, reason="Tesseract is not installed"
)


# -- TSV parsing (no Tesseract needed) -------------------------------------

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def test_words_on_one_line_are_joined():
    text = tsv(
        "5\t1\t1\t1\t1\t1\t100\t200\t60\t20\t96\tHello",
        "5\t1\t1\t1\t1\t2\t170\t200\t70\t20\t95\tworld",
    )
    lines = ocr._lines_from_tsv(text, scale=1.0)
    assert [line.text for line in lines] == ["Hello world"]


def test_different_lines_stay_separate():
    text = tsv(
        "5\t1\t1\t1\t1\t1\t100\t200\t60\t20\t96\tFirst",
        "5\t1\t1\t1\t2\t1\t100\t230\t60\t20\t96\tSecond",
    )
    assert len(ocr._lines_from_tsv(text, scale=1.0)) == 2


def test_low_confidence_words_are_dropped():
    # Speckle on a scan reads as punctuation; translating it produces gibberish.
    text = tsv(
        "5\t1\t1\t1\t1\t1\t100\t200\t60\t20\t96\tReal",
        "5\t1\t1\t1\t1\t2\t170\t200\t10\t20\t3\t~",
    )
    assert [line.text for line in ocr._lines_from_tsv(text, scale=1.0)] == ["Real"]


def test_non_word_rows_are_ignored():
    # Levels 1-4 are page/block/paragraph/line summaries, not words.
    text = tsv(
        "4\t1\t1\t1\t1\t0\t100\t200\t200\t20\t-1\t",
        "5\t1\t1\t1\t1\t1\t100\t200\t60\t20\t96\tWord",
    )
    assert [line.text for line in ocr._lines_from_tsv(text, scale=1.0)] == ["Word"]


def test_pixel_coordinates_are_converted_back_to_points():
    text = tsv("5\t1\t1\t1\t1\t1\t300\t600\t150\t30\t96\tWord")
    # Recognised at 300dpi, so the scale is 300/72.
    line = ocr._lines_from_tsv(text, scale=300 / 72)[0]
    assert line.rect.x0 == pytest.approx(72.0)
    assert line.rect.y0 == pytest.approx(144.0)


def test_empty_output_yields_no_lines():
    assert ocr._lines_from_tsv(tsv(), scale=1.0) == []


def test_malformed_rows_are_skipped_rather_than_crashing():
    text = tsv(
        "5\t1\t1\t1\t1\t1\tnot-a-number\t200\t60\t20\t96\tBad",
        "5\t1\t1\t1\t2\t1\t100\t230\t60\t20\t96\tGood",
    )
    assert [line.text for line in ocr._lines_from_tsv(text, scale=1.0)] == ["Good"]


# -- size estimation -------------------------------------------------------


def test_a_full_span_line_is_measured_against_its_full_height():
    # "Apply happy" runs from ascender to descender: box ≈ 0.93em.
    assert ocr._size_multiplier("Apply happy") == pytest.approx(1.07)


def test_an_all_caps_line_is_scaled_up_from_its_cap_height():
    # Without this, headings come out looking like body copy.
    assert ocr._size_multiplier("ANNUAL REPORT") == pytest.approx(1.32)


def test_a_capital_q_is_not_treated_as_a_descender():
    assert ocr._size_multiplier("QUARTER SUMMARY") == ocr._size_multiplier("ANNUAL REPORT")


def test_an_x_height_only_line_is_scaled_up():
    assert ocr._size_multiplier("nose environs") == pytest.approx(1.32)


# -- against the real Tesseract --------------------------------------------


@needs_tesseract
def test_english_and_german_data_are_installed():
    assert ocr.supports(languages.ENGLISH)
    assert ocr.supports(languages.GERMAN)


@needs_tesseract
def test_a_scanned_page_has_no_text_layer_to_find(scanned_pdf):
    document = pymupdf.open(scanned_pdf)
    assert not extractor.has_usable_text_layer(document[0])
    assert extractor.layout_of(document[0], 0).blocks == []
    document.close()


@needs_tesseract
def test_recognition_finds_the_words_a_scan_contains(scanned_pdf):
    document = pymupdf.open(scanned_pdf)
    layout = ocr.recognise_page(document[0], 0, languages.ENGLISH)
    document.close()

    assert layout.was_recognised
    everything = " ".join(block.joined_text for block in layout.blocks)
    assert "Quarterly Report" in everything
    assert "steady growth" in everything


@needs_tesseract
def test_recognition_recovers_the_headings_size(scanned_pdf):
    document = pymupdf.open(scanned_pdf)
    layout = ocr.recognise_page(document[0], 0, languages.ENGLISH)
    document.close()

    heading = [b for b in layout.blocks if "Quarterly" in b.joined_text]
    body = [b for b in layout.blocks if "steady growth" in b.joined_text]
    assert heading and body
    # The heading was set at 22pt over 10.5pt body; the gap must survive.
    assert heading[0].representative_font_size > body[0].representative_font_size * 1.5


@needs_tesseract
def test_a_scanned_document_translates_end_to_end(scanned_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    engine = StubEngine()
    report = PdfTranslationPipeline().translate(
        scanned_pdf,
        output,
        languages.ENGLISH,
        languages.GERMAN,
        engine,
        options=Options(recognise_scanned_pages=True),
    )
    assert report.used_ocr
    assert report.recognised_pages == [1]

    result = pymupdf.open(output)
    text = result[0].get_text("text")
    result.close()
    # The translation is now a real text layer over the scan.
    assert "[" in text


@needs_tesseract
def test_the_original_scanned_words_are_removed_from_the_image(scanned_pdf, tmp_path):
    """The words on a scan are pixels, not text objects.

    Redaction alone leaves them visible underneath the translation, so the
    renderer has to clear the pixels for OCR'd pages. This checks it does.
    """
    output = tmp_path / "out.pdf"

    # The replacement must share no words with the source, or finding the
    # source text again would prove nothing. Length is matched roughly so the
    # blocks still fill about the same space.
    def replace(text: str) -> str:
        phrase = "Ersatztext ohne Bezug "
        return (phrase * (len(text) // len(phrase) + 1))[: max(len(text), len(phrase))]

    PdfTranslationPipeline().translate(
        scanned_pdf,
        output,
        languages.ENGLISH,
        languages.GERMAN,
        StubEngine(transform=replace),
        options=Options(recognise_scanned_pages=True),
    )

    result = pymupdf.open(output)
    recovered = ocr.recognise_page(result[0], 0, languages.ENGLISH)
    result.close()

    everything = " ".join(block.joined_text for block in recovered.blocks)
    assert "Ersatztext" in everything, "the translation was not drawn onto the page"
    # If the original pixels were still there, OCR would read them back.
    assert "steady growth" not in everything
    assert "Quarterly" not in everything


def test_ocr_reports_why_it_cannot_run(monkeypatch, scanned_pdf):
    monkeypatch.setattr(
        ocr, "availability", lambda: ocr.OcrAvailability(False, "Tesseract is missing.")
    )
    document = pymupdf.open(scanned_pdf)
    with pytest.raises(Exception) as failure:
        ocr.recognise_page(document[0], 0, languages.ENGLISH)
    document.close()
    assert "Tesseract" in str(failure.value)


def test_a_document_still_translates_when_ocr_is_unavailable(monkeypatch, sample_pdf, tmp_path):
    """One unreadable scanned page must not fail a forty-page document."""
    monkeypatch.setattr(
        ocr, "availability", lambda: ocr.OcrAvailability(False, "Tesseract is missing.")
    )
    output = tmp_path / "out.pdf"
    report = PdfTranslationPipeline().translate(
        sample_pdf,
        output,
        languages.ENGLISH,
        languages.GERMAN,
        StubEngine(),
        options=Options(recognise_scanned_pages=True),
    )
    assert report.block_count > 0
    assert output.exists()
