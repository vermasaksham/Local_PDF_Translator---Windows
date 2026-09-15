"""Background threads for the two kinds of translation.

Everything expensive — loading a model, decoding a sentence, rasterising a page
— happens here rather than on the GUI thread, so the window never stops
repainting and the Cancel button always responds.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core import errors
from ..core.engine import TranslationEngine
from ..core.languages import Language
from ..pdf.pipeline import Options, PdfTranslationPipeline, Progress, Report


class _CancellableWorker(QThread):
    """Common cancellation plumbing."""

    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class TextTranslationWorker(_CancellableWorker):
    """Translates the contents of the Text tab."""

    #: The finished translation.
    translated = Signal(str)
    #: Fraction in 0..1.
    progressed = Signal(float)

    def __init__(
        self,
        engine: TranslationEngine,
        text: str,
        source: Language,
        target: Language,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._text = text
        self._source = source
        self._target = target

    def run(self) -> None:
        try:
            result = self._engine.translate(
                self._text,
                self._source,
                self._target,
                progress=self.progressed.emit,
                cancel=self._cancel,
            )
        except errors.TranslationCancelled:
            return  # The user asked for this; nothing to report.
        except Exception as failure:
            if not self.cancelled:
                self.failed.emit(errors.describe(failure))
            return
        if not self.cancelled:
            self.translated.emit(result)


class PdfTranslationWorker(_CancellableWorker):
    """Runs a PDF through the layout-preserving pipeline."""

    #: The finished report.
    completed = Signal(object)
    #: fraction, phase label, detail
    progressed = Signal(float, str, str)

    def __init__(
        self,
        engine: TranslationEngine,
        input_path: Path,
        output_path: Path,
        source: Language,
        target: Language,
        options: Options,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._input = input_path
        self._output = output_path
        self._source = source
        self._target = target
        self._options = options
        self._pipeline = PdfTranslationPipeline()

    def run(self) -> None:
        def on_progress(progress: Progress) -> None:
            self.progressed.emit(progress.fraction, progress.phase, progress.detail)

        try:
            report: Report = self._pipeline.translate(
                self._input,
                self._output,
                self._source,
                self._target,
                self._engine,
                options=self._options,
                progress=on_progress,
                cancel=self._cancel,
            )
        except errors.TranslationCancelled:
            # A half-written output would be worse than none at all.
            self._output.unlink(missing_ok=True)
            return
        except Exception as failure:
            if not self.cancelled:
                self.failed.emit(errors.describe(failure))
            return
        if not self.cancelled:
            self.completed.emit(report)
