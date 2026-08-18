"""Measures and draws the translated text.

Two backends, chosen by the target language's script:

* **Vector** — for Latin text. PyMuPDF writes real, selectable, searchable text
  into the PDF at a fraction of the file size. This is the good path and it is
  what English and German use.

* **Shaped** — for Devanagari. PDF text drawing has no complex-script shaping
  engine: it emits code points in logical order, so `कि` comes out with the
  vowel sign on the wrong side of its consonant, and conjuncts never form. That
  is not a cosmetic problem, it is wrong text. Hindi is therefore laid out by
  Qt's text engine — which shapes complex scripts with its own HarfBuzz — and
  placed as a high-resolution image. The trade-off is that Hindi output is a
  picture of text rather than selectable text: correctness bought at the price
  of searchability.

  Qt rather than Pillow's Raqm layout engine, which was the obvious choice and
  the wrong one: Raqm ships only in Pillow's Linux wheels, so on Windows — the
  platform this app targets — it silently is not there and Devanagari comes out
  unshaped. Qt is already a hard dependency and shapes correctly everywhere.

Both backends expose the same measure/wrap/paint interface so the renderer does
not care which one it is holding.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf

from ..core.languages import Language
from .fonts import FontChoice, font_for
from .layout import Rect

#: The translated text is drawn into an image at this multiple of the PDF's own
#: resolution when shaping is required. 4x of 72dpi is 288dpi — comfortably
#: past the point where the difference is visible in print.
SHAPED_IMAGE_SCALE = 4.0

#: Font size used for cached measurement, then scaled. TrueType advances are
#: linear in size, so one cached face measures every size accurately enough for
#: layout decisions.
_REFERENCE_SIZE = 64.0


def rgb_from_int(colour: int) -> tuple[float, float, float]:
    """Unpack PyMuPDF's 0xRRGGBB span colour into floats in 0..1."""
    return (
        ((colour >> 16) & 0xFF) / 255.0,
        ((colour >> 8) & 0xFF) / 255.0,
        (colour & 0xFF) / 255.0,
    )


@dataclass(frozen=True)
class LineMetrics:
    ascender: float
    descender: float

    @property
    def height(self) -> float:
        return self.ascender + self.descender


class TextPainter:
    """Common measuring and wrapping; subclasses do the drawing."""

    def __init__(self, font: FontChoice) -> None:
        self.font = font

    # -- to be provided by subclasses --------------------------------------

    def text_width(self, text: str, size: float, bold: bool = False) -> float:
        raise NotImplementedError

    def metrics(self, size: float, bold: bool = False) -> LineMetrics:
        raise NotImplementedError

    def paint(
        self,
        page: pymupdf.Page,
        lines: Sequence[str],
        rect: Rect,
        size: float,
        leading: float,
        alignment: str,
        colour: tuple[float, float, float],
        bold: bool = False,
    ) -> None:
        raise NotImplementedError

    # -- shared ------------------------------------------------------------

    def wrap(self, text: str, size: float, max_width: float, bold: bool = False) -> list[str]:
        """Break `text` into lines that fit `max_width`.

        Breaks at spaces, and only inside a word when that single word is
        itself wider than the box — which happens with long URLs and with
        German compounds, and is better than letting one word run off the page.
        """
        if max_width <= 0:
            return [text]

        lines: list[str] = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split(" "):
                if current:
                    candidate = f"{current} {word}"
                    if self.text_width(candidate, size, bold) <= max_width:
                        current = candidate
                        continue
                    lines.append(current)
                    current = ""
                # Starting a fresh line: the word either fits or must be split.
                if self.text_width(word, size, bold) > max_width:
                    pieces = self._split_word(word, size, max_width, bold)
                    lines.extend(pieces[:-1])
                    current = pieces[-1]
                else:
                    current = word
            lines.append(current)
        return lines or [""]

    def _split_word(self, word: str, size: float, max_width: float, bold: bool) -> list[str]:
        pieces: list[str] = []
        current = ""
        for character in word:
            candidate = current + character
            if current and self.text_width(candidate, size, bold) > max_width:
                pieces.append(current)
                current = character
            else:
                current = candidate
        pieces.append(current)
        return pieces or [word]

    def measure_height(
        self, lines: Sequence[str], size: float, leading: float, bold: bool = False
    ) -> float:
        """Height a wrapped block will occupy, from the top of the first line
        to the bottom of the last."""
        if not lines:
            return 0.0
        metrics = self.metrics(size, bold)
        return leading * (len(lines) - 1) + metrics.height


# --------------------------------------------------------------------------
# Vector: real PDF text, for Latin scripts


@lru_cache(maxsize=8)
def _pymupdf_font(path: str) -> pymupdf.Font:
    return pymupdf.Font(fontfile=path)


class VectorTextPainter(TextPainter):
    """Writes selectable text straight into the PDF."""

    def _face(self, bold: bool) -> pymupdf.Font:
        return _pymupdf_font(str(self.font.file_for(bold)))

    def text_width(self, text: str, size: float, bold: bool = False) -> float:
        if not text:
            return 0.0
        return float(self._face(bold).text_length(text, fontsize=size))

    def metrics(self, size: float, bold: bool = False) -> LineMetrics:
        face = self._face(bold)
        # PyMuPDF reports these as fractions of the em, descender negative.
        return LineMetrics(
            ascender=abs(float(face.ascender)) * size,
            descender=abs(float(face.descender)) * size,
        )

    def paint(
        self,
        page: pymupdf.Page,
        lines: Sequence[str],
        rect: Rect,
        size: float,
        leading: float,
        alignment: str,
        colour: tuple[float, float, float],
        bold: bool = False,
    ) -> None:
        if not lines:
            return
        path = str(self.font.file_for(bold))
        alias = _font_alias(path)
        # Registering per page is idempotent in PyMuPDF and keeps one embedded
        # copy per page rather than one per call.
        page.insert_font(fontname=alias, fontfile=path)

        metrics = self.metrics(size, bold)
        for index, line in enumerate(lines):
            if not line:
                continue
            baseline = rect.y0 + metrics.ascender + index * leading
            x = _aligned_x(rect, self.text_width(line, size, bold), alignment)
            page.insert_text(
                (x, baseline),
                line,
                fontname=alias,
                fontsize=size,
                color=colour,
                overlay=True,
            )


def _font_alias(path: str) -> str:
    """A short, stable, PDF-safe name for an embedded font."""
    stem = Path(path).stem
    cleaned = "".join(character for character in stem if character.isalnum())
    return f"LPT{cleaned[:24]}" if cleaned else "LPTFont"


def _aligned_x(rect: Rect, width: float, alignment: str) -> float:
    if alignment == "centre":
        return rect.x0 + max(rect.width - width, 0) / 2
    if alignment == "right":
        return rect.x1 - width
    return rect.x0


# --------------------------------------------------------------------------
# Shaped: HarfBuzz layout rasterised, for Devanagari


def _qt_application():
    """The QGuiApplication that Qt's font machinery needs.

    The app always has one by the time any of this runs. Headless callers (the
    tests, `--self-test`) may not, so one is created on demand — which only
    works on the main thread, hence the explicit error rather than a hang.
    """
    from PySide6.QtGui import QGuiApplication

    existing = QGuiApplication.instance()
    if existing is not None:
        return existing

    import threading

    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "Qt has to be initialised on the main thread before text can be shaped. "
            "Create a QGuiApplication before starting the translation."
        )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QGuiApplication([])


@lru_cache(maxsize=8)
def _qt_family(path: str) -> str:
    """Register a font file with Qt and return the family name it took."""
    from PySide6.QtGui import QFontDatabase

    _qt_application()
    identifier = QFontDatabase.addApplicationFont(path)
    families = QFontDatabase.applicationFontFamilies(identifier)
    if not families:
        raise ShapingUnavailable(f"Qt could not load the font at {path}")
    return families[0]


@lru_cache(maxsize=16)
def _qt_font(path: str, pixel_size: int, bold: bool):
    from PySide6.QtGui import QFont

    font = QFont(_qt_family(path))
    font.setPixelSize(max(pixel_size, 1))
    if bold:
        font.setBold(True)
    # Qt only runs its shaper when it is allowed to lay text out properly;
    # NoFontMerging keeps it from substituting a face that cannot do the job.
    font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
    return font


class ShapingUnavailable(RuntimeError):
    """Devanagari cannot be laid out on this machine."""


@lru_cache(maxsize=1)
def shaping_status() -> tuple[bool, str]:
    """Whether complex-script text really is being shaped, and why not if not.

    A functional check rather than a version check: it lays out a Devanagari
    string that must form a conjunct and compares the result with the width of
    the same code points measured one at a time. If a shaper ran, the two
    disagree. If they match, the glyphs are being emitted in logical order and
    Hindi output would be wrong.

    The reason is returned rather than swallowed because the two ways this
    fails — no Devanagari font, or a font that loads but is not shaped — need
    completely different fixes, and a bare False says nothing about which.
    """
    from PySide6.QtGui import QFontMetricsF

    try:
        choice = font_for_devanagari()
    except Exception as failure:
        return False, f"no Devanagari font could be found ({failure})"

    try:
        _qt_application()
        font = _qt_font(str(choice.regular), int(_REFERENCE_SIZE), False)
        metrics = QFontMetricsF(font)
        shaped = metrics.horizontalAdvance(_SHAPING_PROBE)
        naive = sum(metrics.horizontalAdvance(character) for character in _SHAPING_PROBE)
    except Exception as failure:
        return False, f"Qt could not lay out Devanagari with {choice.regular.name} ({failure})"

    if shaped <= 0:
        return False, f"{choice.regular.name} produced no glyphs for Devanagari"
    if abs(shaped - naive) <= 0.5:
        return False, (
            f"{choice.regular.name} loaded but nothing shaped the text "
            "(vowel signs would sit on the wrong side of their consonants)"
        )
    return True, f"shaped with {choice.regular.name}"


def shaping_available() -> bool:
    return shaping_status()[0]


def release_fonts() -> None:
    """Drop the cached Qt font objects.

    They outlive the QApplication otherwise, and letting the interpreter
    destroy the application first at shutdown is a documented way to crash —
    which would turn a passing run into a non-zero exit long after the work
    was done.
    """
    _qt_font.cache_clear()
    _qt_family.cache_clear()
    shaping_status.cache_clear()


def font_for_devanagari() -> FontChoice:
    from ..core.languages import Script
    from .fonts import font_for_script

    return font_for_script(Script.DEVANAGARI)


#: "ti-ma-hi ri-po-rt" — contains a matra that must be reordered and a
#: consonant cluster that must form a conjunct.
_SHAPING_PROBE = "तिमाही रिपोर्ट"


class ShapedTextPainter(TextPainter):
    """Lays text out with Qt's shaper and places it as a high-resolution image."""

    def __init__(self, font: FontChoice, scale: float = SHAPED_IMAGE_SCALE) -> None:
        super().__init__(font)
        self.scale = scale

    def _metrics_at_reference(self, bold: bool):
        from PySide6.QtGui import QFontMetricsF

        font = _qt_font(str(self.font.file_for(bold)), int(_REFERENCE_SIZE), bold)
        return QFontMetricsF(font)

    def text_width(self, text: str, size: float, bold: bool = False) -> float:
        if not text:
            return 0.0
        # Measured once at a reference size and scaled: advances are linear in
        # size, and this avoids building a face per candidate size during the
        # shrink-to-fit search.
        advance = self._metrics_at_reference(bold).horizontalAdvance(text)
        return float(advance) * size / _REFERENCE_SIZE

    def metrics(self, size: float, bold: bool = False) -> LineMetrics:
        reference = self._metrics_at_reference(bold)
        factor = size / _REFERENCE_SIZE
        return LineMetrics(
            ascender=float(reference.ascent()) * factor,
            descender=float(reference.descent()) * factor,
        )

    def paint(
        self,
        page: pymupdf.Page,
        lines: Sequence[str],
        rect: Rect,
        size: float,
        leading: float,
        alignment: str,
        colour: tuple[float, float, float],
        bold: bool = False,
    ) -> None:
        if not any(lines):
            return

        from PySide6.QtCore import QBuffer, QPointF
        from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter

        _qt_application()

        block_metrics = self.metrics(size, bold)
        block_height = leading * (len(lines) - 1) + block_metrics.height
        # The image covers the text's own extent rather than the whole block,
        # so a short translation does not paint a large transparent rectangle
        # over whatever sits beneath it.
        target = Rect(rect.x0, rect.y0, rect.x1, rect.y0 + block_height)

        width_px = max(round(target.width * self.scale), 1)
        height_px = max(round(target.height * self.scale), 1)
        # A very tall block at high scale can produce an enormous bitmap; cap
        # the pixel budget rather than exhausting memory on a pathological page.
        if width_px * height_px > 40_000_000:  # pragma: no cover - guard
            factor = (40_000_000 / (width_px * height_px)) ** 0.5
            width_px = max(int(width_px * factor), 1)
            height_px = max(int(height_px * factor), 1)

        scale_x = width_px / target.width if target.width else self.scale
        scale_y = height_px / target.height if target.height else self.scale

        image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))

        font = _qt_font(str(self.font.file_for(bold)), max(round(size * scale_y), 1), bold)
        ink = QColor.fromRgbF(*colour)

        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(font)
            painter.setPen(ink)
            ascent = QFontMetricsF(font).ascent()
            for index, line in enumerate(lines):
                if not line:
                    continue
                width_pt = self.text_width(line, size, bold)
                x = (_aligned_x(target, width_pt, alignment) - target.x0) * scale_x
                baseline = ascent + index * leading * scale_y
                painter.drawText(QPointF(x, baseline), line)
        finally:
            painter.end()

        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.ReadWrite)
        image.save(buffer, "PNG")
        data = bytes(buffer.data())
        buffer.close()

        page.insert_image(
            pymupdf.Rect(*target.as_tuple()),
            stream=data,
            keep_proportion=False,
            overlay=True,
        )


# --------------------------------------------------------------------------


def painter_for(language: Language) -> TextPainter:
    """The right painter for a target language."""
    choice = font_for(language)
    if language.script.needs_shaping:
        return ShapedTextPainter(choice)
    return VectorTextPainter(choice)
