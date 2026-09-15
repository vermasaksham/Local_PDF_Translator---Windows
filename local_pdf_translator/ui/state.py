"""Shared, app-wide state: the language selection and the one translation
engine both tabs draw on.

The engine is deliberately shared. Each loaded model is tens of megabytes of
resident weights, and giving each tab its own would double that for no gain.
"""

from __future__ import annotations

import contextlib
import threading

from PySide6.QtCore import QObject, Signal

from ..core import languages
from ..core.engine import TranslationEngine
from ..core.languages import Language
from ..core.model_catalog import ModelCatalog, ModelDescriptor


class AppState(QObject):
    languages_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.catalog = ModelCatalog()
        self.engine = TranslationEngine(self.catalog)
        self._source: Language = languages.ENGLISH
        self._target: Language = languages.GERMAN
        self._preload_thread: threading.Thread | None = None

    # -- languages ---------------------------------------------------------

    @property
    def source(self) -> Language:
        return self._source

    @property
    def target(self) -> Language:
        return self._target

    def set_source(self, language: Language) -> None:
        if language == self._source:
            return
        self._source = language
        # Keep the two pickers off the same language. Whichever one the user
        # did *not* just touch is the one that moves, so their explicit choice
        # always survives.
        if self._target == self._source:
            alternative = languages.first_other_than(self._source)
            if alternative is not None:
                self._target = alternative
        self._selection_changed()

    def set_target(self, language: Language) -> None:
        if language == self._target:
            return
        self._target = language
        if self._source == self._target:
            alternative = languages.first_other_than(self._target)
            if alternative is not None:
                self._source = alternative
        self._selection_changed()

    def swap_languages(self) -> None:
        self._source, self._target = self._target, self._source
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.languages_changed.emit()
        self.preload()

    # -- models ------------------------------------------------------------

    @property
    def missing_models(self) -> list[ModelDescriptor]:
        return self.catalog.missing_models

    @property
    def has_route(self) -> bool:
        return self.catalog.has_route(self._source, self._target)

    @property
    def pivots_through_english(self) -> bool:
        return self.catalog.pivots(self._source, self._target)

    def preload(self) -> None:
        """Warm the models for the current pair on a background thread, so the
        first translation is not stalled behind several hundred milliseconds of
        disk and memory work."""
        if not self.has_route:
            return
        source, target = self._source, self._target

        def warm() -> None:
            # A failure here is not worth reporting: whatever went wrong
            # will be raised again, with context, on the real translation.
            with contextlib.suppress(Exception):
                self.engine.preload(source, target)

        thread = threading.Thread(target=warm, name="preload", daemon=True)
        self._preload_thread = thread
        thread.start()
