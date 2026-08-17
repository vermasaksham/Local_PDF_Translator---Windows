"""Errors the user is expected to see, with the fix attached.

Every error here carries a `recovery` string. The message says what went
wrong; the recovery says what to do about it, which is usually the only part
the reader actually needs.
"""

from __future__ import annotations

from .languages import Language


class LocalTranslatorError(Exception):
    """Base class for everything this app raises deliberately."""

    #: What to do about it. Empty when there is nothing useful to suggest.
    recovery: str = ""

    def display_text(self) -> str:
        """Message and recovery suggestion, ready to put in front of a user."""
        message = str(self)
        return f"{message}\n{self.recovery}" if self.recovery else message


# --------------------------------------------------------------------------
# Translation


class TranslationCancelled(LocalTranslatorError):
    """The user asked to stop. Never worth reporting as a failure."""

    def __init__(self) -> None:
        super().__init__("Translation was cancelled.")


class NoRouteAvailable(LocalTranslatorError):
    """No model, and no chain of models, connects the two languages."""

    def __init__(self, source: Language, target: Language) -> None:
        super().__init__(
            f"No translation model is available for {source.english_name} "
            f"to {target.english_name}."
        )
        self.recovery = (
            "Choose a different language pair, or add the missing model to ModelCatalog."
        )


class ModelMissing(LocalTranslatorError):
    """The catalog advertises a model that is not on disk."""

    def __init__(self, name: str, expected_path: str) -> None:
        super().__init__(
            f"The translation model “{name}” is missing. Expected it at {expected_path}."
        )
        self.recovery = (
            "Run scripts\\fetch_models.py to download and convert the models, "
            "or reinstall the app so the bundled models are restored."
        )


class ModelLoadFailed(LocalTranslatorError):
    """CTranslate2 or SentencePiece refused to load a model."""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"Could not load the translation model “{name}”: {reason}")
        self.recovery = (
            "The model files may be corrupt; re-download them with scripts\\fetch_models.py."
        )


class TranslationFailed(LocalTranslatorError):
    """CTranslate2 failed part-way through."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Translation failed: {reason}")


# --------------------------------------------------------------------------
# PDF


class PdfError(LocalTranslatorError):
    """Base class for PDF-specific failures."""


class CannotOpenDocument(PdfError):
    def __init__(self, path: str, reason: str = "") -> None:
        detail = f" ({reason})" if reason else ""
        super().__init__(f"“{path}” could not be opened as a PDF{detail}.")
        self.recovery = (
            "Check that the file is a PDF and is not still being written by another program."
        )


class DocumentIsEncrypted(PdfError):
    def __init__(self, path: str) -> None:
        super().__init__(f"“{path}” is password protected.")
        self.recovery = (
            "Remove the password (in Acrobat or Edge, print it to a new PDF) and try again."
        )


class DocumentHasNoPages(PdfError):
    def __init__(self) -> None:
        super().__init__("That PDF contains no pages.")


class NoTextFound(PdfError):
    """Every page was image-only, and OCR was off or produced nothing."""

    def __init__(self, attempted_ocr: bool) -> None:
        if attempted_ocr:
            super().__init__(
                "No readable text was found in this PDF, even after running text recognition."
            )
            self.recovery = (
                "The scan may be too low-resolution or too skewed to recognise. "
                "Try a higher-quality scan."
            )
        else:
            super().__init__("This PDF has no text layer — it looks like a scan.")
            self.recovery = (
                "Turn on “Read scanned pages with OCR” in the PDF tab and try again."
            )


class OcrUnavailable(PdfError):
    """Tesseract is not installed or its language data is missing."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Text recognition is not available: {reason}")
        self.recovery = (
            "Reinstall the app (the installer includes Tesseract), or install Tesseract-OCR "
            "and set the LPT_TESSERACT_EXE environment variable to its tesseract.exe."
        )


class RenderingFailed(PdfError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"The translated PDF could not be drawn: {reason}")


class CannotWriteOutput(PdfError):
    def __init__(self, path: str, reason: str = "") -> None:
        detail = f" ({reason})" if reason else ""
        super().__init__(f"The translated PDF could not be written to {path}{detail}.")
        self.recovery = (
            "Choose a different folder, or close the file if it is open in a PDF viewer."
        )


def describe(error: BaseException) -> str:
    """A user-facing string for any exception, ours or not."""
    if isinstance(error, LocalTranslatorError):
        return error.display_text()
    return f"{type(error).__name__}: {error}"
