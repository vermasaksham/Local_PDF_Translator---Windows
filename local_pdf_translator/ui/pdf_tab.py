"""Tab two: drop a PDF on the left, get the translated PDF on the right."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.paths import user_data_directory
from ..pdf import ocr
from ..pdf.pipeline import Options, Report
from .pdf_preview import PdfPreview
from .state import AppState
from .widgets import ErrorNotice, pane
from .workers import PdfTranslationWorker


class PdfTab(QWidget):
    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._worker: PdfTranslationWorker | None = None
        self._input_path: Path | None = None
        self._output_path: Path | None = None

        self._input_preview = PdfPreview(
            "Drop a PDF here, or use “Choose PDF…”.", accepts_drops=True
        )
        self._output_preview = PdfPreview("The translated PDF appears here.")
        self._input_preview.file_dropped.connect(self.load_pdf)

        self._input_title = QLabel()
        self._output_title = QLabel()
        self._input_caption = QLabel("No file chosen")
        self._output_caption = QLabel(" ")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(pane(self._input_title, self._input_preview, self._input_caption))
        splitter.addWidget(pane(self._output_title, self._output_preview, self._output_caption))
        splitter.setSizes([500, 500])
        splitter.setChildrenCollapsible(False)

        self._ocr = QCheckBox("Read scanned pages with OCR")
        recognition = ocr.availability()
        self._ocr.setChecked(recognition.available)
        self._ocr.setEnabled(recognition.available)
        self._ocr.setToolTip(
            "For pages that are pictures rather than text, recognise the words first."
            if recognition.available
            else f"Unavailable: {recognition.reason}"
        )

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        self._phase = QLabel("")
        self._phase.setObjectName("caption")
        self._error = ErrorNotice()

        self._choose = QPushButton("Choose PDF…")
        self._translate = QPushButton("Translate")
        self._translate.setObjectName("primary")
        self._translate.setDefault(True)
        self._cancel = QPushButton("Cancel")
        self._cancel.setVisible(False)
        self._save = QPushButton("Save translated PDF…")
        self._save.setEnabled(False)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._choose)
        controls.addWidget(self._ocr)
        controls.addStretch(1)
        controls.addWidget(self._cancel)
        controls.addWidget(self._save)
        controls.addWidget(self._translate)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._progress)
        layout.addWidget(self._phase)
        layout.addWidget(self._error)
        layout.addLayout(controls)

        self._choose.clicked.connect(self.choose_file)
        self._translate.clicked.connect(self.translate)
        self._cancel.clicked.connect(self._cancel_translation)
        self._save.clicked.connect(self._save_output)
        self._state.languages_changed.connect(self._languages_changed)

        self.setAcceptDrops(True)
        self._languages_changed()
        self._refresh_buttons()

    # -- loading -----------------------------------------------------------

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a PDF to translate", "", "PDF documents (*.pdf)"
        )
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str) -> None:
        self._input_path = Path(path)
        self._input_preview.load(path)
        self._input_caption.setText(self._input_path.name)
        self._clear_output()
        self._error.hide_notice()
        self._refresh_buttons()

    def _clear_output(self) -> None:
        self._output_preview.clear()
        self._output_path = None
        self._output_caption.setText(" ")
        self._save.setEnabled(False)
        self._phase.setText("")

    # -- translating -------------------------------------------------------

    def translate(self) -> None:
        if self._input_path is None or not self._state.has_route:
            return
        self._cancel_translation()
        self._error.hide_notice()
        self._clear_output()

        # Written somewhere private first; the user names it only if they
        # decide to keep it.
        scratch = user_data_directory() / "output"
        scratch.mkdir(parents=True, exist_ok=True)
        output = scratch / f"{self._input_path.stem}.{self._state.target.code}.pdf"

        options = Options(recognise_scanned_pages=self._ocr.isChecked())
        worker = PdfTranslationWorker(
            self._state.engine,
            self._input_path,
            output,
            self._state.source,
            self._state.target,
            options,
            self,
        )
        worker.progressed.connect(self._progressed)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        self._set_busy(True)
        worker.start()

    def _cancel_translation(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        self._worker = None

    def shutdown(self) -> None:
        """Stop any work in flight, so the window can close promptly."""
        self._cancel_translation()

    # -- callbacks ---------------------------------------------------------

    def _progressed(self, fraction: float, phase: str, detail: str) -> None:
        self._progress.setValue(int(fraction * 100))
        self._phase.setText(f"{phase} — {detail}" if detail else phase)

    def _completed(self, report: Report) -> None:
        self._output_path = report.output_path
        self._output_preview.load(report.output_path)
        self._output_caption.setText("Ready to save")
        self._save.setEnabled(True)
        self._phase.setText(_summary(report))
        if report.ocr_warning:
            self._error.show_message(report.ocr_warning, tone="warning")

    def _failed(self, message: str) -> None:
        self._error.show_message(message)
        self._phase.setText("")

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._cancel.setVisible(busy)
        self._translate.setEnabled(not busy and self._can_translate())
        self._choose.setEnabled(not busy)
        self._ocr.setEnabled(not busy)
        if busy:
            self._progress.setValue(0)

    def _languages_changed(self) -> None:
        self._input_title.setText(f"Original — {self._state.source.native_name}")
        self._output_title.setText(f"Translated — {self._state.target.native_name}")
        self._output_preview.set_placeholder("The translated PDF appears here.")
        self._clear_output()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self._translate.setEnabled(self._can_translate())

    def _can_translate(self) -> bool:
        return self._input_path is not None and self._state.has_route

    # -- saving ------------------------------------------------------------

    def _save_output(self) -> None:
        if self._output_path is None or not self._output_path.exists():
            return
        suggested = ""
        if self._input_path is not None:
            suggested = str(
                self._input_path.with_name(
                    f"{self._input_path.stem}.{self._state.target.code}.pdf"
                )
            )
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save the translated PDF", suggested, "PDF documents (*.pdf)"
        )
        if not destination:
            return
        try:
            shutil.copyfile(self._output_path, destination)
        except OSError as failure:
            self._error.show_message(f"The file could not be saved: {failure}")
            return
        self._output_caption.setText(f"Saved to {Path(destination).name}")

    # -- drag and drop over the whole tab ----------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if any(
            url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.load_pdf(url.toLocalFile())
                event.acceptProposedAction()
                return


def _summary(report: Report) -> str:
    """A one-line account of what the run actually did."""
    parts = [
        f"{report.page_count} page{'' if report.page_count == 1 else 's'}",
        f"{report.block_count} block{'' if report.block_count == 1 else 's'} translated",
    ]
    if report.recognised_pages:
        parts.append(f"{len(report.recognised_pages)} page(s) read with OCR")
    if report.skipped_pages:
        parts.append(
            f"{len(report.skipped_pages)} page(s) had no text and were left as they were"
        )
    if report.overflowed_blocks:
        # Honest about the one thing that can look wrong on the page.
        parts.append(f"{report.overflowed_blocks} block(s) were too long to fit and run on")
    return " · ".join(parts)
