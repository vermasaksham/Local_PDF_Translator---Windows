"""Splits text into units small enough for an NMT model to translate well.

OPUS-MT models are trained on single sentences and degrade badly when handed a
whole paragraph — they truncate, or silently drop clauses. Everything is
therefore translated a sentence at a time and stitched back together, with the
original whitespace and paragraph breaks preserved exactly.

The segmenter is pure Python on purpose: it is the piece most likely to need
tuning per language, and it must stay unit-testable without loading a model.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .languages import Language

# Words that end in a full stop without ending a sentence. Stored without the
# dot and lower-cased. English and German both appear here because a document
# in one language routinely quotes the other.
_ABBREVIATIONS: frozenset[str] = frozenset(
    [
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "st",
        "jr",
        "sr",
        "vs",
        "etc",
        "al",
        "fig",
        "figs",
        "no",
        "nos",
        "vol",
        "vols",
        "pp",
        "ed",
        "eds",
        "approx",
        "dept",
        "est",
        "inc",
        "ltd",
        "co",
        "corp",
        "univ",
        "ave",
        "blvd",
        "rd",
        "apt",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sept",
        "sep",
        "oct",
        "nov",
        "dec",
        "mon",
        "tue",
        "tues",
        "wed",
        "thu",
        "thur",
        "thurs",
        "fri",
        "sat",
        "sun",
        "herr",
        "frau",
        "dr",
        "med",
        "dipl",
        "ing",
        "bzw",
        "ggf",
        "evtl",
        "inkl",
        "exkl",
        "usw",
        "sog",
        "vgl",
        "ebd",
        "abb",
        "tab",
        "nr",
        "abs",
        "art",
        "kap",
        "str",
        "hrsg",
        "jh",
        "jhd",
        "bspw",
    ]
)

# Single capital letters ("J. R. R. Tolkien") are initials, never sentence ends.
_INITIAL = re.compile(r"(?:^|[\s(\[\"'])([A-ZÀ-Þ])$")

# A terminator run, plus any closing punctuation that belongs to the sentence.
_TERMINATOR_RUN = re.compile(r"[.!?…]+[\"'”’)\]»]*|[।॥]+[\"'”’)\]]*")

# Characters that can legitimately start the next sentence.
_SENTENCE_START = re.compile(r"[\"'“‘(\[«ऀ-ॿ\dA-ZÀ-Þ]")

_DIGIT_BEFORE_DOT = re.compile(r"\d$")


@dataclass(frozen=True)
class Piece:
    """A run of the input: either text to translate, or a separator to keep."""

    text: str
    translatable: bool

    @staticmethod
    def to_translate(text: str) -> Piece:
        return Piece(text, True)

    @staticmethod
    def verbatim(text: str) -> Piece:
        return Piece(text, False)


class SentenceSegmenter:
    """Breaks text into sentences and puts it back together again losslessly."""

    def __init__(self, maximum_sentence_length: int = 900) -> None:
        # Sentences longer than this are split further at clause boundaries.
        # Chosen to sit comfortably under the models' 512-token positional limit.
        self.maximum_sentence_length = maximum_sentence_length

    # -- public API --------------------------------------------------------

    def segment(self, text: str, language: Language) -> list[Piece]:
        """Break `text` into translatable sentences interleaved with the exact
        whitespace that separated them, so that reassembly is lossless."""
        if not text:
            return []

        pieces: list[Piece] = []
        # Paragraph breaks carry meaning (and layout); never let the sentence
        # splitter merge across them.
        for chunk, is_break in _split_keeping_separators(
            text, lambda c: c == "\n" or c == "\r"
        ):
            if is_break:
                pieces.append(Piece.verbatim(chunk))
            else:
                pieces.extend(self._segment_paragraph(chunk, language))
        return pieces

    @staticmethod
    def reassemble(pieces: Sequence[Piece]) -> str:
        """Rejoin the output of `segment` after substitution."""
        return "".join(piece.text for piece in pieces)

    # -- internals ---------------------------------------------------------

    def _segment_paragraph(self, paragraph: str, language: Language) -> list[Piece]:
        if not paragraph.strip():
            return [Piece.verbatim(paragraph)] if paragraph else []

        pieces: list[Piece] = []
        cursor = 0

        for start, end in _sentence_spans(paragraph):
            if cursor < start:
                # Whitespace (and anything else) between sentences is kept exactly.
                pieces.append(Piece.verbatim(paragraph[cursor:start]))
            sentence = paragraph[start:end]
            leading = len(sentence) - len(sentence.lstrip())
            if leading:
                pieces.append(Piece.verbatim(sentence[:leading]))
                sentence = sentence[leading:]
            trailing = len(sentence) - len(sentence.rstrip())
            tail = sentence[len(sentence) - trailing :] if trailing else ""
            if trailing:
                sentence = sentence[: len(sentence) - trailing]
            if sentence:
                pieces.extend(Piece.to_translate(part) for part in self._split_long(sentence))
            if tail:
                pieces.append(Piece.verbatim(tail))
            cursor = end

        if cursor < len(paragraph):
            tail = paragraph[cursor:]
            # A trailing run is usually whitespace, but a paragraph with no
            # sentence-ending punctuation lands here too and must be translated.
            pieces.append(
                Piece.verbatim(tail) if not tail.strip() else Piece.to_translate(tail)
            )

        return pieces or [Piece.to_translate(paragraph)]

    def _split_long(self, sentence: str) -> list[str]:
        """Split a run-on sentence at clause boundaries, then at word
        boundaries if that is still not enough.

        Only splits inside a word when that one word is itself over the limit,
        which means it is not really a word.
        """
        if len(sentence) <= self.maximum_sentence_length:
            return [sentence]

        chunks: list[str] = []
        current = ""
        # Semicolons and commas are the least damaging places to cut: the model
        # still sees a syntactically plausible fragment on either side.
        for clause in _split_after(sentence, ";,।"):
            if current and len(current) + len(clause) > self.maximum_sentence_length:
                chunks.append(current)
                current = ""
            if len(clause) > self.maximum_sentence_length:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_on_words(clause))
            else:
                current += clause
        if current:
            chunks.append(current)
        return chunks or [sentence]

    def _split_on_words(self, text: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for word in text.split(" "):
            if current and len(current) + len(word) + 1 > self.maximum_sentence_length:
                chunks.append(current)
                current = ""
            if len(word) > self.maximum_sentence_length:
                # A single token longer than the limit — a base64 blob, a long
                # URL, a run of joined text from a broken PDF. Splitting it
                # mid-token loses nothing that was there to begin with, and
                # passing it through whole would overrun the model's positional
                # limit and corrupt everything after it in the batch.
                chunks.extend(
                    word[index : index + self.maximum_sentence_length]
                    for index in range(0, len(word), self.maximum_sentence_length)
                )
                continue
            current = word if not current else f"{current} {word}"
        if current:
            chunks.append(current)
        return chunks


# --------------------------------------------------------------------------
# Boundary detection


def _sentence_spans(paragraph: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) offsets of each sentence in a single paragraph."""
    start = 0
    for match in _TERMINATOR_RUN.finditer(paragraph):
        end = match.end()
        if not _is_boundary(paragraph, match):
            continue
        if end > start:
            yield start, end
        start = end
    if start < len(paragraph):
        yield start, len(paragraph)


def _is_boundary(paragraph: str, match: re.Match[str]) -> bool:
    text = match.group()
    end = match.end()

    # The Devanagari danda is unambiguous — it has no abbreviation use.
    if text[0] in "।॥":
        return True

    # Must be followed by whitespace or the end of the paragraph. "3.5" and
    # "www.example.com" fail here, which is the point.
    after = paragraph[end:]
    if after and not after[0].isspace():
        return False

    # "!" and "?" are never abbreviation markers, so they always end a sentence.
    if text[0] != ".":
        return True

    before = paragraph[: match.start()]
    if _DIGIT_BEFORE_DOT.search(before):
        # "Clause 4." at the end of a paragraph is a sentence; "4. Januar" is not.
        return not after.strip() or _looks_like_new_sentence(after)
    if _INITIAL.search(before):
        return False

    word = re.split(r"[\s(\[\"']", before)[-1].lower().strip(".")
    if word in _ABBREVIATIONS:
        return False
    # An unbroken run of single letters and dots ("e.g", "z.B", "u.s.w") is an
    # abbreviation rather than a string of one-letter sentences.
    if re.fullmatch(r"(?:\w\.)+\w", word):
        return False

    return not after.strip() or _looks_like_new_sentence(after)


def _looks_like_new_sentence(after: str) -> bool:
    stripped = after.lstrip()
    return bool(stripped) and bool(_SENTENCE_START.match(stripped[0]))


# --------------------------------------------------------------------------
# Small helpers


def _split_keeping_separators(text: str, is_separator) -> Iterator[tuple[str, bool]]:
    """Split into alternating runs of non-separator and separator characters."""
    current = ""
    current_is_separator: bool | None = None
    for character in text:
        separator = is_separator(character)
        if separator != current_is_separator and current:
            yield current, bool(current_is_separator)
            current = ""
        current_is_separator = separator
        current += character
    if current:
        yield current, bool(current_is_separator)


def _split_after(text: str, separators: str) -> list[str]:
    """Split after each separator, keeping the separator on the left piece."""
    pieces: list[str] = []
    current = ""
    for character in text:
        current += character
        if character in separators:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces
