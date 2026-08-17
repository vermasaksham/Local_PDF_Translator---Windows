"""Verify that a packaged build is actually complete.

Run with `LocalPDFTranslator.exe --self-test`. This is what the build pipeline
uses to catch the failures that a compile cannot: models left out of the
bundle, a Pillow without Raqm, a missing Devanagari font. Each of those
produces an app that starts perfectly well and is then wrong or useless, so
they are worth an explicit check.

Exits 0 when everything a user needs is present.
"""

from __future__ import annotations

import sys
import traceback

from . import APP_NAME, __version__
from .core import languages
from .core.engine import TranslationEngine
from .core.model_catalog import ModelCatalog
from .core.paths import models_directory, resource_root


class _Results:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        mark = "ok  " if condition else "FAIL"
        print(f"  [{mark}] {name}{f' — {detail}' if detail else ''}")
        if not condition:
            self.failures.append(name)
        return condition

    def warn(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            print(f"  [ok  ] {name}{f' — {detail}' if detail else ''}")
        else:
            print(f"  [warn] {name}{f' — {detail}' if detail else ''}")
            self.warnings.append(name)
        return condition


def run() -> int:
    print(f"{APP_NAME} {__version__} — self test")
    print(f"  resources: {resource_root()}")
    print(f"  models:    {models_directory()}\n")
    results = _Results()

    # -- models
    print("Translation models")
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
    print("\nTranslation engine")
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
    print("\nText rendering")
    from .pdf import fonts
    from .pdf.textpainter import shaping_available

    for language in languages.ALL:
        try:
            choice = fonts.font_for(language)
            results.check(f"font for {language.english_name}", True, choice.regular.name)
        except Exception as failure:
            results.check(f"font for {language.english_name}", False, str(failure))
    # Not a warning: without shaping, Hindi output is wrong rather than ugly.
    results.check(
        "Devanagari shaping (Pillow/Raqm)",
        shaping_available(),
        "" if shaping_available() else "Hindi would render incorrectly",
    )

    # -- OCR is optional; the app is still useful without it
    print("\nText recognition (optional)")
    from .pdf import ocr

    availability = ocr.availability()
    results.warn("Tesseract available", availability.available, availability.reason)
    if availability.available:
        for language in languages.ALL:
            results.warn(f"{language.english_name} language data", ocr.supports(language))

    # -- the interface
    print("\nInterface")
    try:
        from PySide6.QtWidgets import QApplication

        from .ui.main_window import MainWindow

        application = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.close()
        del window
        del application
        results.check("window builds", True)
    except Exception as failure:
        results.check("window builds", False, str(failure))
        traceback.print_exc()

    print()
    if results.failures:
        print(f"FAILED: {len(results.failures)} check(s) — {', '.join(results.failures)}")
        return 1
    if results.warnings:
        print(f"PASSED with {len(results.warnings)} warning(s).")
    else:
        print("PASSED: everything is present.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
