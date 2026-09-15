"""Drives a PDF from source file to translated, layout-preserving output."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..core import errors
from ..core.engine import TranslationEngine
from ..core.languages import Language
from . import extractor, ocr
from .layout import PageLayout
from .renderer import TranslatedPdfRenderer
from .textpainter import painter_for

#: Phase labels, shown under the progress bar.
READING = "Reading the document"
RECOGNISING = "Reading scanned pages"
TRANSLATING = "Translating"
RENDERING = "Drawing the translated PDF"
SAVING = "Saving"

# How the run is divided up on the progress bar. Extraction is quick unless OCR
# is involved; translation dominates everything else.
_EXTRACTION_SHARE = 0.15
_TRANSLATION_SHARE = 0.70


@dataclass
class Progress:
    phase: str
    #: Overall completion in 0..1.
    fraction: float
    #: Extra detail, e.g. "page 3 of 12".
    detail: str = ""


ProgressCallback = Callable[[Progress], None]


@dataclass
class Options:
    #: Run OCR on pages that have no embedded text layer.
    recognise_scanned_pages: bool = True
    #: 1-based inclusive page range. None means the whole document.
    page_range: tuple[int, int] | None = None


@dataclass
class Report:
    """What happened, beyond the output file itself."""

    output_path: Path
    page_count: int
    block_count: int
    #: Pages whose text came from OCR rather than an embedded text layer.
    recognised_pages: list[int] = field(default_factory=list)
    #: Pages left untouched because no text could be found on them.
    skipped_pages: list[int] = field(default_factory=list)
    #: Blocks whose translation would not fit even at the minimum size and were
    #: allowed to run on into the space below.
    overflowed_blocks: int = 0
    #: Set when OCR was wanted but could not run, with the reason.
    ocr_warning: str = ""

    @property
    def used_ocr(self) -> bool:
        return bool(self.recognised_pages)


class PdfTranslationPipeline:
    def __init__(self, renderer: TranslatedPdfRenderer | None = None) -> None:
        self.renderer = renderer or TranslatedPdfRenderer()

    def translate(
        self,
        input_path: str | Path,
        output_path: str | Path,
        source: Language,
        target: Language,
        engine: TranslationEngine,
        options: Options | None = None,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> Report:
        options = options or Options()
        input_path = Path(input_path)
        output_path = Path(output_path)

        document = _open(input_path)
        try:
            return self._run(
                document,
                input_path,
                output_path,
                source,
                target,
                engine,
                options,
                progress,
                cancel,
            )
        finally:
            document.close()

    # -- the run -----------------------------------------------------------

    def _run(
        self,
        document: pymupdf.Document,
        input_path: Path,
        output_path: Path,
        source: Language,
        target: Language,
        engine: TranslationEngine,
        options: Options,
        progress: ProgressCallback | None,
        cancel: threading.Event | None,
    ) -> Report:
        if document.page_count == 0:
            raise errors.DocumentHasNoPages()

        _report(progress, READING, 0.0)

        indices = _page_indices(options, document.page_count)

        # Rotation is switched off for the whole run so that extraction (which
        # reports rotated coordinates) and drawing (which expects unrotated
        # ones) share a single space. The original values go back on before the
        # file is written, so the output opens the same way up as the input.
        rotations = {index: document[index].rotation for index in indices}
        for index, rotation in rotations.items():
            if rotation:
                document[index].set_rotation(0)

        try:
            layouts, recognised, skipped, warning = self._extract(
                document, indices, source, options, progress, cancel
            )

            total_blocks = sum(len(layout.blocks) for layout in layouts)
            if total_blocks == 0:
                raise errors.NoTextFound(attempted_ocr=options.recognise_scanned_pages)

            translations = self._translate_blocks(
                layouts, source, target, engine, progress, cancel
            )
            overflowed = self._render(document, layouts, translations, target, progress, cancel)
        finally:
            for index, rotation in rotations.items():
                if rotation:
                    document[index].set_rotation(rotation)

        _raise_if_cancelled(cancel)
        _report(progress, SAVING, 0.98)
        _save(document, output_path)
        _report(progress, SAVING, 1.0)

        return Report(
            output_path=output_path,
            page_count=len(layouts),
            block_count=total_blocks,
            recognised_pages=recognised,
            skipped_pages=skipped,
            overflowed_blocks=overflowed,
            ocr_warning=warning,
        )

    # -- 1. extract --------------------------------------------------------

    def _extract(
        self,
        document: pymupdf.Document,
        indices: Sequence[int],
        source: Language,
        options: Options,
        progress: ProgressCallback | None,
        cancel: threading.Event | None,
    ) -> tuple[list[PageLayout], list[int], list[int], str]:
        layouts: list[PageLayout] = []
        recognised: list[int] = []
        skipped: list[int] = []
        warning = ""

        for position, index in enumerate(indices):
            _raise_if_cancelled(cancel)
            page = document[index]
            layout = extractor.layout_of(page, index)

            # Either nothing was found, or so little that the page is really a
            # scan carrying a stray watermark.
            looks_scanned = not layout.blocks or not extractor.has_usable_text_layer(page)
            if looks_scanned and options.recognise_scanned_pages:
                _report(
                    progress,
                    RECOGNISING,
                    _EXTRACTION_SHARE * position / max(len(indices), 1),
                    f"page {index + 1} of {document.page_count}",
                )
                try:
                    recognised_layout = ocr.recognise_page(page, index, source)
                except errors.OcrUnavailable as failure:
                    # Record it once and carry on with whatever text layer the
                    # rest of the document has, rather than failing a 40-page
                    # document over one scanned page.
                    warning = warning or failure.display_text()
                    recognised_layout = None
                if recognised_layout is not None and recognised_layout.blocks:
                    layout = recognised_layout
                    recognised.append(index + 1)

            if not layout.blocks:
                skipped.append(index + 1)
            layouts.append(layout)

        return layouts, recognised, skipped, warning

    # -- 2. translate ------------------------------------------------------

    def _translate_blocks(
        self,
        layouts: Sequence[PageLayout],
        source: Language,
        target: Language,
        engine: TranslationEngine,
        progress: ProgressCallback | None,
        cancel: threading.Event | None,
    ) -> list[list[str]]:
        _report(progress, TRANSLATING, _EXTRACTION_SHARE)

        # Every block on every page goes through in one pooled pass, so
        # repeated headers and footers are translated once for the whole
        # document and the decoder never runs an under-filled batch.
        texts = [block.joined_text for layout in layouts for block in layout.blocks]

        def on_progress(fraction: float) -> None:
            _report(
                progress,
                TRANSLATING,
                _EXTRACTION_SHARE + fraction * _TRANSLATION_SHARE,
            )

        translated = engine.translate_all(
            texts, source, target, progress=on_progress, cancel=cancel
        )

        # Redistribute back onto their pages.
        result: list[list[str]] = []
        cursor = 0
        for layout in layouts:
            count = len(layout.blocks)
            result.append(list(translated[cursor : cursor + count]))
            cursor += count
        return result

    # -- 3. render ---------------------------------------------------------

    def _render(
        self,
        document: pymupdf.Document,
        layouts: Sequence[PageLayout],
        translations: Sequence[Sequence[str]],
        target: Language,
        progress: ProgressCallback | None,
        cancel: threading.Event | None,
    ) -> int:
        base = _EXTRACTION_SHARE + _TRANSLATION_SHARE
        span = 1.0 - base - 0.02  # the last slice belongs to saving
        # One painter for the whole document: it caches the font face, and for
        # Hindi that means one HarfBuzz face rather than one per page.
        painter = painter_for(target)
        overflowed = 0

        for position, (layout, page_translations) in enumerate(
            zip(layouts, translations, strict=True)
        ):
            _raise_if_cancelled(cancel)
            _report(
                progress,
                RENDERING,
                base + span * position / max(len(layouts), 1),
                f"page {layout.page_index + 1} of {document.page_count}",
            )
            if not layout.blocks:
                continue
            page = document[layout.page_index]
            result = self.renderer.render_page(page, layout, page_translations, target, painter)
            overflowed += result.overflowed

        return overflowed


# --------------------------------------------------------------------------
# Helpers


def _open(path: Path) -> pymupdf.Document:
    try:
        document = pymupdf.open(path)
    except Exception as failure:
        raise errors.CannotOpenDocument(path.name, str(failure)) from failure

    if document.needs_pass:
        document.close()
        raise errors.DocumentIsEncrypted(path.name)
    if not document.is_pdf:
        document.close()
        raise errors.CannotOpenDocument(path.name, "it is not a PDF")
    return document


def _save(document: pymupdf.Document, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Subsetting keeps the embedded font down to the glyphs actually used,
        # which matters when a whole Devanagari face would otherwise be carried.
        with contextlib.suppress(Exception):  # optional optimisation
            document.subset_fonts()
        document.save(
            str(output_path),
            garbage=4,
            deflate=True,
            clean=True,
        )
    except Exception as failure:
        raise errors.CannotWriteOutput(str(output_path), str(failure)) from failure


def _page_indices(options: Options, page_count: int) -> list[int]:
    if not options.page_range:
        return list(range(page_count))
    first, last = options.page_range
    lower = max(first - 1, 0)
    upper = min(last - 1, page_count - 1)
    if lower > upper:
        return list(range(page_count))
    return list(range(lower, upper + 1))


def _report(
    progress: ProgressCallback | None, phase: str, fraction: float, detail: str = ""
) -> None:
    if progress is not None:
        progress(Progress(phase, max(0.0, min(fraction, 1.0)), detail))


def _raise_if_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise errors.TranslationCancelled()
