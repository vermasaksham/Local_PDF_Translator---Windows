"""Verify that a packaged build is actually complete.

Run with `LocalPDFTranslator.exe --self-test`. This is what the build pipeline
uses to catch the failures that a compile cannot: models left out of the
bundle, a missing Devanagari font, a Qt that will not shape. Each of those
produces an app that starts perfectly well and is then wrong or useless, so
they are worth an explicit check.

Exits 0 when everything a user needs is present.
"""

from __future__ import annotations

import contextlib
import sys
import traceback

from . import APP_NAME, __version__
from .core import languages
from .core.engine import TranslationEngine
from .core.model_catalog import ModelCatalog
from .core.paths import models_directory, resource_root


def _say(message: str = "") -> None:
    """Print a line and push it out immediately.

    Unbuffered because this runs as the last gate before an installer is
    built: if it dies, the output explaining how far it got must already have
    reached the log, not be sitting in a buffer that the crash discards.
    """
    print(message, flush=True)


def _use_unicode_output() -> None:
    """Make stdout able to carry the text this test deliberately prints.

    A Windows console defaults to a legacy code page — cp1252 on an English
    install — which has no Devanagari at all. The self-test prints the Hindi
    translation it just produced, so without this it dies with
    UnicodeEncodeError at the exact moment it is reporting success.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


class _Results:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        mark = "ok  " if condition else "FAIL"
        _say(f"  [{mark}] {name}{f' — {detail}' if detail else ''}")
        if not condition:
            self.failures.append(name)
        return condition

    def warn(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            _say(f"  [ok  ] {name}{f' — {detail}' if detail else ''}")
        else:
            _say(f"  [warn] {name}{f' — {detail}' if detail else ''}")
            self.warnings.append(name)
        return condition


def _start_qt():
    """Create the QApplication the rest of the checks need.

    It has to be a QApplication rather than a QGuiApplication, because the
    interface check builds a real QWidget. And it has to happen first: the
    shaping check would otherwise create a QGuiApplication of its own, and
    every later QWidget would fail against it.
    """
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def run() -> int:
    _use_unicode_output()
    _start_qt()
    _say(f"{APP_NAME} {__version__} — self test")
    _say(f"  resources: {resource_root()}")
    _say(f"  models:    {models_directory()}\n")
    results = _Results()

    # -- models
    _say("Translation models")
    catalog = ModelCatalog()
    missing = catalog.missing_models
    results.check(
        "all models present",
        not missing,
        ", ".join(model.directory_name for model in missing) or f"{len(catalog.models)} models",
    )
    for source in languages.ALL:
        for target in languages.ALL:
            if source is target:
                continue
            results.check(
                f"route {source.code}->{target.code}",
                catalog.has_route(source, target),
            )

    # -- a real translation, which is the only way to know the runtime loaded
    _say("\nTranslation engine")
    if not missing:
        try:
            engine = TranslationEngine(catalog)
            output = engine.translate(
                "The meeting begins at nine o'clock.",
                languages.ENGLISH,
                languages.GERMAN,
            )
            results.check("English to German", bool(output.strip()), repr(output))
            output = engine.translate(
                "The meeting begins at nine o'clock.",
                languages.ENGLISH,
                languages.HINDI,
            )
            results.check("English to Hindi", bool(output.strip()), repr(output))
        except Exception as failure:
            results.check("engine runs", False, str(failure))
            traceback.print_exc()
    else:
        results.check("engine runs", False, "skipped, models are missing")

    # -- text rendering
    _say("\nText rendering")
    from .pdf import fonts
    from .pdf.textpainter import shaping_status

    for language in languages.ALL:
        try:
            choice = fonts.font_for(language)
            results.check(f"font for {language.english_name}", True, choice.regular.name)
        except Exception as failure:
            results.check(f"font for {language.english_name}", False, str(failure))
    # Not a warning: without shaping, Hindi output is wrong rather than ugly.
    shapes, reason = shaping_status()
    results.check("Devanagari shaping (Qt)", shapes, reason)

    # -- OCR is optional; the app is still useful without it
    _say("\nText recognition (optional)")
    from .pdf import ocr

    availability = ocr.availability()
    results.warn("Tesseract available", availability.available, availability.reason)
    if availability.available:
        for language in languages.ALL:
            results.warn(f"{language.english_name} language data", ocr.supports(language))

    # -- the interface
    _say("\nInterface")
    try:
        from .ui.main_window import MainWindow

        window = MainWindow()
        window.close()
        del window
        results.check("window builds", True)
    except Exception as failure:
        results.check("window builds", False, str(failure))
        traceback.print_exc()

    _say()
    if results.failures:
        _say(f"FAILED: {len(results.failures)} check(s) — {', '.join(results.failures)}")
        return 1
    if results.warnings:
        _say(f"PASSED with {len(results.warnings)} warning(s).")
    else:
        _say("PASSED: everything is present.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
