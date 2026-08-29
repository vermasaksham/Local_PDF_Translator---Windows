"""Shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from local_pdf_translator.core import languages
from local_pdf_translator.core.model_catalog import BUNDLED, ModelCatalog


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Devanagari is shaped by Qt, and Qt insists on being started from the
    main thread. The real app has a QApplication long before any of this runs;
    the tests have to make one themselves."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    application = QGuiApplication.instance() or QGuiApplication([])
    yield application


class StubEngine:
    """Stands in for the real engine so the PDF pipeline can be tested without
    a gigabyte of model weights.

    Records what it was asked to translate, which is usually the thing under
    test: the pipeline's job is to hand the engine the right strings and put
    the answers back in the right places.
    """

    def __init__(self, transform=None) -> None:
        self.seen: list[str] = []
        self.calls = 0
        self._transform = transform or (lambda text: f"[{text}]")

    def translate_all(self, texts, source, target, progress=None, cancel=None):
        self.calls += 1
        self.seen.extend(texts)
        if progress is not None:
            progress(1.0)
        return [self._transform(text) for text in texts]

    def translate(self, text, source, target, progress=None, cancel=None):
        return self.translate_all([text], source, target, progress, cancel)[0]


@pytest.fixture
def stub_engine():
    return StubEngine()


@pytest.fixture
def installed_catalog(tmp_path) -> ModelCatalog:
    """A catalog whose every model is present on disk."""
    for model in BUNDLED:
        directory = tmp_path / model.directory_name
        directory.mkdir(parents=True)
        for name in ("model.bin", "source.spm", "target.spm"):
            (directory / name).write_bytes(b"")
    return ModelCatalog(models_directory=tmp_path)


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """A one-page document with a heading, two columns, a banner and a rule."""
    path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)

    page.insert_text((72, 90), "Quarterly Report", fontname="hebo", fontsize=22)
    page.insert_textbox(
        pymupdf.Rect(72, 110, 300, 260),
        "The company delivered steady growth across all regions during the quarter. "
        "Revenue rose by eleven percent compared with the same period last year.",
        fontname="helv",
        fontsize=10.5,
    )
    page.insert_textbox(
        pymupdf.Rect(320, 110, 523, 260),
        "The board has approved an increased dividend. "
        "Shareholders will receive payment in the first week of next month.",
        fontname="helv",
        fontsize=10.5,
    )
    # A tinted banner with reversed-out type, and a rule: both are things the
    # renderer must leave alone.
    page.draw_rect(pymupdf.Rect(72, 300, 523, 340), color=None, fill=(0.15, 0.25, 0.55))
    page.insert_text(
        (84, 326),
        "Outlook remains positive",
        fontname="hebo",
        fontsize=14,
        color=(1, 1, 1),
    )
    page.draw_line(
        pymupdf.Point(72, 360), pymupdf.Point(523, 360), color=(0.6, 0.6, 0.6), width=1
    )
    document.save(path)
    document.close()
    return path


@pytest.fixture
def scanned_pdf(tmp_path, sample_pdf) -> Path:
    """The same document flattened to an image, so it has no text layer."""
    path = tmp_path / "scanned.pdf"
    source = pymupdf.open(sample_pdf)
    pixmap = source[0].get_pixmap(dpi=200)
    source.close()

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pixmap)
    document.save(path)
    document.close()
    return path


@pytest.fixture
def english():
    return languages.ENGLISH


@pytest.fixture
def german():
    return languages.GERMAN
