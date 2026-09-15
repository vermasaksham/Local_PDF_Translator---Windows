"""The source/target language selector shared by both tabs."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from ..core import languages
from .state import AppState


class LanguageBar(QWidget):
    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._updating = False

        self._source = QComboBox()
        self._target = QComboBox()
        for combo in (self._source, self._target):
            for language in languages.ALL:
                combo.addItem(f"{language.native_name}", language.code)
            combo.setMinimumWidth(150)

        self._swap = QPushButton("⇄")
        self._swap.setToolTip("Swap the two languages")
        self._swap.setFixedWidth(40)
        self._swap.setAccessibleName("Swap languages")

        self._note = QLabel("")
        self._note.setObjectName("pivotNote")
        self._note.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Translate from"))
        layout.addWidget(self._source)
        layout.addWidget(self._swap)
        layout.addWidget(QLabel("into"))
        layout.addWidget(self._target)
        layout.addWidget(self._note, 1)

        self._source.currentIndexChanged.connect(self._source_changed)
        self._target.currentIndexChanged.connect(self._target_changed)
        self._swap.clicked.connect(self._state.swap_languages)
        self._state.languages_changed.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        self._source.setCurrentIndex(self._source.findData(self._state.source.code))
        self._target.setCurrentIndex(self._target.findData(self._state.target.code))
        self._updating = False

        if not self._state.has_route:
            self._note.setText("No model is installed for this pair.")
            self._note.setProperty("tone", "warning")
        elif self._state.pivots_through_english:
            # Worth saying: two hops is slower, and each one compounds the
            # translation error of the last.
            self._note.setText("Translated via English — slower, and a little less exact.")
            self._note.setProperty("tone", "info")
        else:
            self._note.setText("")
            self._note.setProperty("tone", "")
        style = self._note.style()
        style.unpolish(self._note)
        style.polish(self._note)

    def _source_changed(self, index: int) -> None:
        if self._updating:
            return
        language = languages.named(self._source.itemData(index))
        if language is not None:
            self._state.set_source(language)

    def _target_changed(self, index: int) -> None:
        if self._updating:
            return
        language = languages.named(self._target.itemData(index))
        if language is not None:
            self._state.set_target(language)
