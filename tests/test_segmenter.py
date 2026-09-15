"""The segmenter must never lose or reorder a character."""

from __future__ import annotations

import pytest

from local_pdf_translator.core import languages
from local_pdf_translator.core.segmenter import SentenceSegmenter


@pytest.fixture
def segmenter():
    return SentenceSegmenter()


def sentences(segmenter, text, language=languages.ENGLISH):
    return [piece.text for piece in segmenter.segment(text, language) if piece.translatable]


# -- losslessness ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "One sentence.",
        "One. Two. Three.",
        "Ragged   spacing.   And   more.",
        "Line one\nLine two\n\nParagraph two.",
        "\n\n\nleading newlines",
        "trailing newlines\n\n\n",
        "No terminator at all",
        "Mixed\r\nWindows\r\nline endings.",
        "यह पहला वाक्य है। यह दूसरा है।",
        "   ",
    ],
)
def test_reassembly_is_lossless(segmenter, text):
    """Whatever the segmenter takes apart, it must be able to put back exactly."""
    pieces = segmenter.segment(text, languages.ENGLISH)
    assert SentenceSegmenter.reassemble(pieces) == text


def test_reassembly_is_lossless_after_substitution(segmenter):
    text = "First one. Second one.\n\nThird one."
    pieces = segmenter.segment(text, languages.ENGLISH)
    swapped = [type(piece)("X", True) if piece.translatable else piece for piece in pieces]
    # Only the translatable parts change; every separator survives untouched.
    assert SentenceSegmenter.reassemble(swapped) == "X X\n\nX"


# -- boundaries ------------------------------------------------------------


def test_splits_on_ordinary_terminators(segmenter):
    assert sentences(segmenter, "One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_paragraph_breaks_are_never_crossed(segmenter):
    result = sentences(segmenter, "A heading\nSome body text.")
    assert result == ["A heading", "Some body text."]


@pytest.mark.parametrize(
    "text",
    [
        "Dr. Smith arrived early.",
        "See Fig. 4 for details.",
        "The result was 3.5 percent.",
        "Contact us at www.example.com today.",
        "Written by J. R. R. Tolkien in 1937.",
        "Das gilt bzw. trifft zu.",
        "Die Kosten sind ca. zehn Euro.",
    ],
)
def test_abbreviations_do_not_end_a_sentence(segmenter, text):
    assert sentences(segmenter, text) == [text]


def test_lower_case_after_a_dot_is_not_a_new_sentence(segmenter):
    # A sentence never starts with a lower-case letter, so this is one unit.
    assert sentences(segmenter, "version 2.0 beta was released") == [
        "version 2.0 beta was released"
    ]


def test_danda_always_ends_a_hindi_sentence(segmenter):
    result = sentences(segmenter, "यह पहला है। यह दूसरा है।", languages.HINDI)
    assert result == ["यह पहला है।", "यह दूसरा है।"]


def test_quotation_marks_stay_with_their_sentence(segmenter):
    assert sentences(segmenter, '"Stop now." She left.') == ['"Stop now."', "She left."]


def test_trailing_sentence_without_terminator_is_still_translated(segmenter):
    assert sentences(segmenter, "Complete. Incomplete") == ["Complete.", "Incomplete"]


# -- long input ------------------------------------------------------------


def test_long_sentences_are_split_at_clause_boundaries():
    segmenter = SentenceSegmenter(maximum_sentence_length=60)
    text = "alpha beta gamma, delta epsilon zeta, eta theta iota, kappa lambda mu."
    pieces = sentences(segmenter, text)
    assert len(pieces) > 1
    assert all(len(piece) <= 60 for piece in pieces)
    assert "".join(pieces) == text


def test_a_single_enormous_word_is_split_rather_than_dropped():
    segmenter = SentenceSegmenter(maximum_sentence_length=20)
    text = "x" * 65
    pieces = sentences(segmenter, text)
    assert "".join(pieces) == text
    assert all(len(piece) <= 20 for piece in pieces)


def test_short_text_is_never_split():
    segmenter = SentenceSegmenter(maximum_sentence_length=1000)
    text = "A perfectly ordinary sentence, with a comma in it."
    assert sentences(segmenter, text) == [text]
