"""The application window: a language bar over two tabs."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..core import languages
from ..core.model_catalog import ModelDescriptor
from ..pdf import ocr
from ..pdf.textpainter import shaping_available
from .language_bar import LanguageBar
from .pdf_tab import PdfTab
from .state import AppState
from .text_tab import TextTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 780)
        self.setMinimumSize(820, 560)

        self.state = AppState()
        self._settings = QSettings("LocalPDFTranslator", "app")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        for banner in self._startup_banners():
            layout.addWidget(banner)

        layout.addWidget(LanguageBar(self.state))

        self.text_tab = TextTab(self.state)
        self.pdf_tab = PdfTab(self.state)
        self._tabs = QTabWidget()
        self._tabs.addTab(self.text_tab, "Text")
        self._tabs.addTab(self.pdf_tab, "PDF")
        layout.addWidget(self._tabs, 1)

        self.setCentralWidget(central)
        self._build_menu()
        self._restore_settings()

        # Warm the default pair so the first translation is not the slowest.
        self.state.preload()

    # -- chrome ------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open PDF…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_pdf)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction(f"&About {APP_NAME}", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    def _open_pdf(self) -> None:
        self._tabs.setCurrentWidget(self.pdf_tab)
        self.pdf_tab.choose_file()

    def _about(self) -> None:
        recognition = ocr.availability()
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}"
            "<p>Translates text and PDF documents entirely on this computer. "
            "Nothing is uploaded and no account or API key is needed.</p>"
            f"<p>Languages: {', '.join(language.english_name for language in languages.ALL)}.<br>"
            "Translation models: Helsinki-NLP OPUS-MT, run with CTranslate2.<br>"
            f"Text recognition: {'Tesseract ' + ', '.join(recognition.languages) if recognition.available else 'unavailable'}.</p>",
        )

    def _startup_banners(self) -> list[QFrame]:
        """Warnings about the installation itself, shown permanently rather
        than as a transient alert: these are conditions the user has to act on
        before anything will work."""
        banners: list[QFrame] = []

        missing = self.state.missing_models
        if missing:
            banners.append(
                _banner(
                    f"{len(missing)} translation model"
                    f"{' is' if len(missing) == 1 else 's are'} missing",
                    "Run scripts\\fetch_models.py, or reinstall the app. Missing: "
                    + ", ".join(model.directory_name for model in _sorted(missing)),
                )
            )

        if not shaping_available():
            # Without Raqm, Devanagari would be drawn with its vowel signs in
            # the wrong places — wrong text, not merely ugly text.
            banners.append(
                _banner(
                    "Hindi output will not be shaped correctly",
                    "This build of Pillow has no Raqm support, so Devanagari conjuncts and "
                    "vowel signs cannot be positioned properly. Reinstall Pillow from a "
                    "standard wheel (pip install --force-reinstall pillow).",
                )
            )

        return banners

    # -- settings ----------------------------------------------------------

    def _restore_settings(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        source = languages.named(str(self._settings.value("source", "en")))
        target = languages.named(str(self._settings.value("target", "de")))
        if source is not None:
            self.state.set_source(source)
        if target is not None:
            self.state.set_target(target)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("source", self.state.source.code)
        self._settings.setValue("target", self.state.target.code)
        # Threads hold the models open; stopping them first keeps the window
        # from lingering on screen after the user has closed it.
        self.text_tab.shutdown()
        self.pdf_tab.shutdown()
        super().closeEvent(event)


def _sorted(models: list[ModelDescriptor]) -> list[ModelDescriptor]:
    return sorted(models, key=lambda model: model.directory_name)


def _banner(title: str, detail: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("banner")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)

    icon = QLabel("⚠")
    icon.setAlignment(Qt.AlignmentFlag.AlignTop)

    body = QVBoxLayout()
    body.setSpacing(2)
    heading = QLabel(f"<b>{title}</b>")
    message = QLabel(detail)
    message.setWordWrap(True)
    body.addWidget(heading)
    body.addWidget(message)

    layout.addWidget(icon)
    layout.addLayout(body, 1)
    return frame
