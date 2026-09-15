"""End-to-end: a real PDF in, a real translated PDF out.

These are the tests that actually prove the promise on the tin — that the
output says something different and looks the same.
"""

from __future__ import annotations

import threading

import pymupdf
import pytest
from conftest import StubEngine

from local_pdf_translator.core import errors, languages
from local_pdf_translator.pdf import extractor
from local_pdf_translator.pdf.pipeline import Options, PdfTranslationPipeline


@pytest.fixture
def pipeline():
    return PdfTranslationPipeline()


def translate(pipeline, source_path, tmp_path, engine=None, **kwargs):
    engine = engine or StubEngine()
    output = tmp_path / "out.pdf"
    report = pipeline.translate(
        source_path,
        output,
        languages.ENGLISH,
        languages.GERMAN,
        engine,
        options=Options(recognise_scanned_pages=False),
        **kwargs,
    )
    return report, engine


# -- extraction ------------------------------------------------------------


def test_the_engine_is_handed_whole_paragraphs_not_lines(pipeline, sample_pdf, tmp_path):
    _, engine = translate(pipeline, sample_pdf, tmp_path)
    # A model given "the quick brown" and "fox jumps over" separately produces
    # nonsense; it must see the joined sentence.
    assert any("delivered steady growth across all regions" in text for text in engine.seen)


def test_the_two_columns_are_not_run_together(pipeline, sample_pdf, tmp_path):
    _, engine = translate(pipeline, sample_pdf, tmp_path)
    # No single block may contain text from both columns.
    for text in engine.seen:
        assert not ("delivered steady growth" in text and "approved an increased" in text)


def test_the_heading_is_its_own_block(pipeline, sample_pdf, tmp_path):
    _, engine = translate(pipeline, sample_pdf, tmp_path)
    assert "Quarterly Report" in engine.seen


def test_everything_is_translated_in_one_pooled_pass(pipeline, sample_pdf, tmp_path):
    _, engine = translate(pipeline, sample_pdf, tmp_path)
    # One call for the whole document keeps the decoder saturated and lets
    # repeated headers and footers be translated once.
    assert engine.calls == 1


# -- output ----------------------------------------------------------------


def test_the_output_carries_the_translation_and_not_the_original(
    pipeline, sample_pdf, tmp_path
):
    report, _ = translate(pipeline, sample_pdf, tmp_path)
    document = pymupdf.open(report.output_path)
    text = document[0].get_text("text")
    document.close()

    assert "[Quarterly Report]" in text
    # The original text objects are removed, not merely covered over.
    assert "Quarterly Report" not in text.replace("[Quarterly Report]", "")


def test_the_output_text_layer_is_searchable(pipeline, sample_pdf, tmp_path):
    report, _ = translate(pipeline, sample_pdf, tmp_path)
    document = pymupdf.open(report.output_path)
    # Latin output is real text, not a picture of text.
    assert document[0].search_for("[Quarterly Report]")
    document.close()


def test_vector_artwork_survives(pipeline, sample_pdf, tmp_path):
    before = pymupdf.open(sample_pdf)
    original_drawings = len(before[0].get_drawings())
    before.close()

    report, _ = translate(pipeline, sample_pdf, tmp_path)
    after = pymupdf.open(report.output_path)
    # The tinted banner and the rule must both still be there.
    assert len(after[0].get_drawings()) == original_drawings
    after.close()


def test_page_geometry_is_unchanged(pipeline, sample_pdf, tmp_path):
    report, _ = translate(pipeline, sample_pdf, tmp_path)
    document = pymupdf.open(report.output_path)
    assert document[0].rect.width == pytest.approx(595, abs=1)
    assert document[0].rect.height == pytest.approx(842, abs=1)
    document.close()


def test_blocks_stay_roughly_where_they_were(pipeline, sample_pdf, tmp_path):
    before = pymupdf.open(sample_pdf)
    # A list, not a dict keyed by y: the two columns start on the same line.
    original = [
        (block.rect.y0, block.rect.x0) for block in extractor.layout_of(before[0], 0).blocks
    ]
    before.close()

    report, _ = translate(pipeline, sample_pdf, tmp_path)
    after = pymupdf.open(report.output_path)
    translated = extractor.layout_of(after[0], 0).blocks
    after.close()

    # Every translated block must start within a few points of where some
    # original block started; nothing has been shuffled around the page.
    for block in translated:
        assert any(
            abs(block.rect.y0 - top) < 6 and abs(block.rect.x0 - left) < 6
            for top, left in original
        ), f"block at {block.rect.as_tuple()} is not where anything used to be"


def test_reversed_out_white_text_stays_white(pipeline, sample_pdf, tmp_path):
    report, _ = translate(pipeline, sample_pdf, tmp_path)
    document = pymupdf.open(report.output_path)
    layout = extractor.layout_of(document[0], 0)
    document.close()

    banner = [block for block in layout.blocks if "Outlook" in block.joined_text]
    assert banner, "the banner text is missing from the output"
    # Redrawing it in black would make it unreadable on the dark banner.
    assert banner[0].color == 0xFFFFFF


def test_a_bold_heading_is_still_bold(pipeline, sample_pdf, tmp_path):
    report, _ = translate(pipeline, sample_pdf, tmp_path)
    document = pymupdf.open(report.output_path)
    layout = extractor.layout_of(document[0], 0)
    document.close()

    heading = [block for block in layout.blocks if "Quarterly" in block.joined_text]
    assert heading and heading[0].bold


def test_rotation_is_preserved(pipeline, tmp_path):
    path = tmp_path / "rotated.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(
        pymupdf.Rect(72, 72, 500, 200),
        "A rotated page with several words of body text on it.",
        fontname="helv",
        fontsize=12,
    )
    page.set_rotation(90)
    document.save(path)
    document.close()

    report, _ = translate(pipeline, path, tmp_path)
    result = pymupdf.open(report.output_path)
    assert result[0].rotation == 90
    assert "[" in result[0].get_text("text")
    result.close()


def test_the_report_counts_what_it_did(pipeline, sample_pdf, tmp_path):
    report, engine = translate(pipeline, sample_pdf, tmp_path)
    assert report.page_count == 1
    assert report.block_count == len(engine.seen)
    assert report.skipped_pages == []
    assert not report.used_ocr


# -- options ---------------------------------------------------------------


def test_a_page_range_limits_what_is_translated(pipeline, tmp_path):
    path = tmp_path / "three-pages.pdf"
    document = pymupdf.open()
    for index in range(3):
        page = document.new_page(width=595, height=842)
        page.insert_textbox(
            pymupdf.Rect(72, 72, 500, 200),
            f"This is the text of page number {index + 1} of the document.",
            fontname="helv",
            fontsize=12,
        )
    document.save(path)
    document.close()

    engine = StubEngine()
    output = tmp_path / "out.pdf"
    report = pipeline.translate(
        path,
        output,
        languages.ENGLISH,
        languages.GERMAN,
        engine,
        options=Options(recognise_scanned_pages=False, page_range=(2, 2)),
    )
    assert report.page_count == 1
    assert all("page number 2" in text for text in engine.seen)

    result = pymupdf.open(output)
    # Pages outside the range are still in the file, untouched.
    assert result.page_count == 3
    assert "page number 1" in result[0].get_text("text")
    assert "[" in result[1].get_text("text")
    result.close()


# -- failures --------------------------------------------------------------


def test_a_missing_file_is_reported_clearly(pipeline, tmp_path):
    with pytest.raises(errors.CannotOpenDocument):
        translate(pipeline, tmp_path / "nope.pdf", tmp_path)


def test_a_document_with_no_text_is_reported_clearly(pipeline, tmp_path):
    path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page(width=595, height=842)
    document.save(path)
    document.close()

    with pytest.raises(errors.NoTextFound) as failure:
        translate(pipeline, path, tmp_path)
    # The message must tell the user about the OCR switch they did not use.
    assert "OCR" in failure.value.display_text()


def test_an_encrypted_document_is_reported_clearly(pipeline, sample_pdf, tmp_path):
    path = tmp_path / "locked.pdf"
    document = pymupdf.open(sample_pdf)
    document.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    document.close()

    with pytest.raises(errors.DocumentIsEncrypted):
        translate(pipeline, path, tmp_path)


def test_cancelling_stops_the_run_and_leaves_no_half_written_file(
    pipeline, sample_pdf, tmp_path
):
    cancel = threading.Event()
    cancel.set()
    output = tmp_path / "cancelled.pdf"

    with pytest.raises(errors.TranslationCancelled):
        pipeline.translate(
            sample_pdf,
            output,
            languages.ENGLISH,
            languages.GERMAN,
            StubEngine(),
            options=Options(recognise_scanned_pages=False),
            cancel=cancel,
        )
    assert not output.exists()


def test_progress_runs_forwards_and_reaches_the_end(pipeline, sample_pdf, tmp_path):
    seen: list[float] = []
    translate(pipeline, sample_pdf, tmp_path, progress=lambda p: seen.append(p.fraction))

    assert seen
    assert seen == sorted(seen), "progress went backwards"
    assert seen[-1] == pytest.approx(1.0)
    assert all(0.0 <= fraction <= 1.0 for fraction in seen)


def test_an_empty_translation_leaves_the_original_text_alone(pipeline, sample_pdf, tmp_path):
    # A model that returns nothing must not silently erase the document.
    engine = StubEngine(transform=lambda text: "")
    report, _ = translate(pipeline, sample_pdf, tmp_path, engine=engine)

    document = pymupdf.open(report.output_path)
    text = document[0].get_text("text")
    document.close()
    assert "Quarterly Report" in text
