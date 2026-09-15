"""Application bootstrap."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME, __version__
from ..core.paths import resource_root
from .main_window import MainWindow
from .theme import stylesheet


def _install_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID.

    Without one, a Python-hosted app is grouped on the taskbar under the Python
    launcher and shows its icon instead of ours.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LocalPDFTranslator.App")
    except Exception:  # pragma: no cover - cosmetic only
        pass


def build_application(argv: list[str] | None = None) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationName("LocalPDFTranslator")
    # Fusion renders the stylesheet consistently across Windows 10 and 11,
    # where the native style ignores several of the properties used here.
    application.setStyle("Fusion")
    application.setStyleSheet(stylesheet(application.palette()))

    icon_path = resource_root() / "assets" / "icon.ico"
    if icon_path.exists():
        application.setWindowIcon(QIcon(str(icon_path)))
    return application


def main(argv: list[str] | None = None) -> int:
    arguments = (argv if argv is not None else sys.argv)[1:]

    if "--self-test" in arguments:
        # Checks that a packaged build is complete. Kept here rather than in a
        # separate executable so it tests the very binary that ships.
        from ..selftest import run

        return run()
    if "--version" in arguments:
        print(f"{APP_NAME} {__version__}")
        return 0

    _install_windows_app_id()
    application = build_application(argv)
    window = MainWindow()
    window.show()

    # A PDF passed on the command line (or via the right-click verb the
    # installer registers) goes straight into the PDF tab.
    for argument in arguments:
        if argument.lower().endswith(".pdf") and os.path.exists(argument):
            window.pdf_tab.load_pdf(argument)
            break

    return application.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
