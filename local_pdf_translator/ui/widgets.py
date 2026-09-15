"""Small shared widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class ErrorNotice(QFrame):
    """Shows a message and its recovery suggestion.

    The recovery suggestion is usually the only part the reader needs, so it is
    shown inline rather than hidden behind a details button.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("errorNotice")
        self._label = QLabel("")
        self._label.setWordWrap(True)
        # Selectable so a user can copy the message into a bug report.
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self._label, 1)
        self.setVisible(False)

    def show_message(self, message: str, tone: str = "error") -> None:
        self._label.setText(message)
        self.setProperty("tone", tone)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.setVisible(True)

    def hide_notice(self) -> None:
        self._label.clear()
        self.setVisible(False)


def pane(title: QLabel, body: QWidget, footer: QLabel | None) -> QWidget:
    """A titled box: heading above, content in the middle, caption below."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    title.setObjectName("paneTitle")
    layout.addWidget(title)
    layout.addWidget(body, 1)
    if footer is not None:
        footer.setObjectName("caption")
        layout.addWidget(footer)
    return container
