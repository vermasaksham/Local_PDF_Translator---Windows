"""Tab one: type or paste text on the left, read the translation on the right."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .state import AppState
from .widgets import ErrorNotice, pane
from .workers import TextTranslationWorker


class TextTab(QWidget):
    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._worker: TextTranslationWorker | None = None

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type or paste the text to translate.")
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        # Read-only, but still selectable so the result can be copied by hand.
        self._output.setPlaceholderText("The translation appears here.")

        self._input_title = QLabel()
        self._output_title = QLabel()
        self._counter = QLabel("0 characters")
        self._counter.setObjectName("caption")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(pane(self._input_title, self._input, self._counter))
        splitter.addWidget(pane(self._output_title, self._output, None))
        splitter.setSizes([500, 500])
        splitter.setChildrenCollapsible(False)

        self._error = ErrorNotice()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        self._progress.setFixedWidth(160)
        self._progress.setTextVisible(False)

        self._clear = QPushButton("Clear")
        self._copy = QPushButton("Copy translation")
        self._cancel = QPushButton("Cancel")
        self._cancel.setVisible(False)
        self._translate = QPushButton("Translate")
        self._translate.setDefault(True)
        self._translate.setObjectName("primary")
        self._translate.setToolTip("Translate the text (Ctrl+Enter)")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._clear)
        controls.addWidget(self._copy)
        controls.addStretch(1)
        controls.addWidget(self._progress)
        controls.addWidget(self._cancel)
        controls.addWidget(self._translate)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._error)
        layout.addLayout(controls)

        self._input.textChanged.connect(self._input_changed)
        self._clear.clicked.connect(self._clear_all)
        self._copy.clicked.connect(self._copy_output)
        self._translate.clicked.connect(self.translate)
        self._cancel.clicked.connect(self._cancel_translation)
        self._state.languages_changed.connect(self._languages_changed)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self.translate)
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(self.translate)

        self._languages_changed()
        self._input_changed()

    # -- actions -----------------------------------------------------------

    def translate(self) -> None:
        text = self._input.toPlainText()
        if not text.strip() or not self._state.has_route:
            return
        self._cancel_translation()
        self._error.hide_notice()
        self._set_busy(True)

        worker = TextTranslationWorker(
            self._state.engine, text, self._state.source, self._state.target, self
        )
        worker.translated.connect(self._finished)
        worker.failed.connect(self._failed)
        worker.progressed.connect(lambda f: self._progress.setValue(int(f * 100)))
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        worker.start()

    def _cancel_translation(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._worker = None

    def shutdown(self) -> None:
        """Stop any work in flight, so the window can close promptly."""
        self._cancel_translation()

    # -- callbacks ---------------------------------------------------------

    def _finished(self, translation: str) -> None:
        self._output.setPlainText(translation)

    def _failed(self, message: str) -> None:
        self._output.clear()
        self._error.show_message(message)

    def _set_busy(self, busy: bool) -> None:
        self._translate.setEnabled(not busy and self._can_translate())
        self._cancel.setVisible(busy)
        self._progress.setVisible(busy)
        if busy:
            self._progress.setValue(0)

    def _languages_changed(self) -> None:
        self._input_title.setText(self._state.source.native_name)
        self._output_title.setText(self._state.target.native_name)
        # A translation of the previous pair would be quietly misleading now.
        self._output.clear()
        self._error.hide_notice()
        self._input_changed()

    def _input_changed(self) -> None:
        count = len(self._input.toPlainText())
        self._counter.setText(f"{count} character{'' if count == 1 else 's'}")
        self._translate.setEnabled(self._can_translate())
        self._copy.setEnabled(bool(self._output.toPlainText()))
        self._clear.setEnabled(bool(count or self._output.toPlainText()))

    def _can_translate(self) -> bool:
        return bool(self._input.toPlainText().strip()) and self._state.has_route

    def _clear_all(self) -> None:
        self._input.clear()
        self._output.clear()
        self._error.hide_notice()

    def _copy_output(self) -> None:
        text = self._output.toPlainText()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._copy.setText("Copied")
        QTimer.singleShot(1500, lambda: self._copy.setText("Copy translation"))
