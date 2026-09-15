"""A small PDF viewer, used for both the original and the translated document."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

#: Pages are rendered at this multiple of the widget width so they stay crisp
#: on a high-DPI display without rendering the whole document at print scale.
_OVERSAMPLE = 1.5


class PdfPreview(QWidget):
    """Shows one page at a time, fitted to the widget's width."""

    #: Emitted when a file is dropped onto the preview.
    file_dropped = Signal(str)

    def __init__(self, placeholder: str, accepts_drops: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._document: pymupdf.Document | None = None
        self._path: Path | None = None
        self._page_index = 0
        self._placeholder = placeholder
        self._rendered_width = 0

        self._page_label = QLabel(placeholder)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setWordWrap(True)
        self._page_label.setObjectName("previewPage")
        self._page_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._page_label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setObjectName("previewArea")

        self._previous = QPushButton("‹")
        self._previous.setFixedWidth(32)
        self._previous.clicked.connect(lambda: self.show_page(self._page_index - 1))
        self._next = QPushButton("›")
        self._next.setFixedWidth(32)
        self._next.clicked.connect(lambda: self.show_page(self._page_index + 1))
        self._counter = QLabel("")
        self._counter.setObjectName("pageCounter")

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self._previous)
        controls.addWidget(self._next)
        controls.addWidget(self._counter)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._scroll, 1)
        layout.addLayout(controls)

        self._update_controls()

        if accepts_drops:
            self.setAcceptDrops(True)

    # -- document ----------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def load(self, path: str | Path) -> None:
        self.clear()
        self._path = Path(path)
        try:
            self._document = pymupdf.open(self._path)
        except Exception:
            self._document = None
            self._page_label.setText("This file could not be previewed.")
            return
        self._page_index = 0
        self._render()
        self._update_controls()

    def clear(self) -> None:
        if self._document is not None:
            self._document.close()
        self._document = None
        self._path = None
        self._page_index = 0
        self._rendered_width = 0
        self._page_label.setPixmap(QPixmap())
        self._page_label.setMinimumHeight(0)
        self._page_label.setText(self._placeholder)
        self._update_controls()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        if self._document is None:
            self._page_label.setText(text)

    def show_page(self, index: int) -> None:
        if self._document is None:
            return
        self._page_index = max(0, min(index, self._document.page_count - 1))
        self._render()
        self._update_controls()

    # -- rendering ---------------------------------------------------------

    def _render(self) -> None:
        if self._document is None or self._document.page_count == 0:
            return
        page = self._document[self._page_index]
        if page.rect.width <= 0 or page.rect.height <= 0:
            return

        viewport = self._scroll.viewport()
        available_width = max(viewport.width() - 24, 120)
        available_height = max(viewport.height() - 24, 120)
        # Fitted to the whole box rather than just the width. The point of this
        # preview is to judge whether the layout survived translation, and a
        # page cropped to its top third does not answer that question.
        scale = min(available_width / page.rect.width, available_height / page.rect.height)
        target_width = max(int(page.rect.width * scale), 1)

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale * _OVERSAMPLE, scale * _OVERSAMPLE),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        # QImage does not take ownership of the buffer, and the PyMuPDF pixmap
        # is freed as soon as this scope ends, so the copy is not optional.
        image = QImage(
            pixmap.samples,
            pixmap.width,
            pixmap.height,
            pixmap.stride,
            QImage.Format.Format_RGB888,
        ).copy()

        rendered = QPixmap.fromImage(image).scaledToWidth(
            target_width, Qt.TransformationMode.SmoothTransformation
        )
        self._page_label.setText("")
        self._page_label.setPixmap(rendered)
        # Without a minimum height the label is sized to the viewport and the
        # page is silently cropped instead of becoming scrollable.
        self._page_label.setMinimumHeight(rendered.height())
        self._scroll.verticalScrollBar().setValue(0)
        self._rendered_width = available_width

    def _update_controls(self) -> None:
        has_document = self._document is not None and self._document.page_count > 0
        count = self._document.page_count if has_document else 0
        self._previous.setEnabled(has_document and self._page_index > 0)
        self._next.setEnabled(has_document and self._page_index < count - 1)
        self._counter.setText(f"Page {self._page_index + 1} of {count}" if has_document else "")
        self._previous.setVisible(has_document)
        self._next.setVisible(has_document)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        # Re-render only on a real width change, not on every stray resize.
        if self._document is not None:
            width = max(self._scroll.viewport().width() - 24, 120)
            if abs(width - self._rendered_width) > 8:
                self._render()

    # -- drag and drop -----------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if _dropped_pdf(event) is not None:
            event.acceptProposedAction()
            self.setProperty("dropTarget", True)
            self._restyle()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.setProperty("dropTarget", False)
        self._restyle()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        path = _dropped_pdf(event)
        self.setProperty("dropTarget", False)
        self._restyle()
        if path is not None:
            event.acceptProposedAction()
            self.file_dropped.emit(path)

    def _restyle(self) -> None:
        # Qt does not re-evaluate a property selector until the style is
        # explicitly reapplied.
        style = self.style()
        style.unpolish(self)
        style.polish(self)


def _dropped_pdf(event) -> str | None:
    """The path of a single dropped PDF, or None if the drop is not one."""
    data = event.mimeData()
    if not data.hasUrls():
        return None
    for url in data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith(".pdf"):
            return path
    return None
