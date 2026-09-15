"""Reads text off scanned pages with Tesseract.

A scanned PDF has no text layer at all — the page is one big image — so there
is nothing for the extractor to find. Tesseract is invoked directly rather than
through a wrapper library: the app already ships the binary, and the TSV output
gives word boxes grouped into lines, which is exactly the shape the layout
analyser wants.
"""

from __future__ import annotations

import csv
import io
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import pymupdf

from ..core import errors, paths
from ..core.languages import Language
from .analyser import blocks_from_lines
from .layout import PageLayout, Rect, TextLine, union_of

#: Scanned text recognises far better at 300dpi than at the 72dpi the page is
#: nominally drawn at.
RECOGNITION_DPI = 300.0

#: Tesseract's confidence scale is 0-100; anything below this is usually noise
#: picked out of speckle, and translating it produces gibberish.
MINIMUM_CONFIDENCE = 40.0

# An OCR'd line box hugs the ink, so its height is not the point size: it is
# whatever vertical span the line's particular letters happen to cover. These
# multipliers convert that span back to a point size. They were measured
# against renderings of known size rather than derived from font metrics,
# because Tesseract's word boxes carry a little padding of their own and come
# out taller than the theoretical x-height. Getting this wrong is very visible
# — a heading recovered at 0.75x looks like body copy.
#
# Measured spans, as a fraction of the em:
#   "Apply happy grading"  ascender to descender   0.93  -> 1.07
#   "ANNUAL REPORT"        cap height only         0.76  -> 1.32
#   "ranges spare grasp"   x-height plus descender 0.76  -> 1.31
#   "nose environs mean"   x-height only           0.76  -> 1.32
# Everything short of a full ascender-to-descender line lands in one place, so
# there are only two cases worth distinguishing.
_SIZE_FULL_SPAN = 1.07
_SIZE_PARTIAL_SPAN = 1.32

# Q is deliberately absent: its tail barely dips below the baseline, and
# counting it as a descender makes all-caps headings come out a sixth too small.
_DESCENDERS = set("gjpqy,;()[]{}/\\")
_ASCENDERS = set("bdfhklt0123456789")

_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class OcrAvailability:
    available: bool
    reason: str = ""
    executable: str = ""
    languages: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def availability() -> OcrAvailability:
    """Whether OCR can run at all, and which language data is installed.

    Cached because it shells out, and the answer cannot change while the app
    is running.
    """
    executable = paths.tesseract_executable()
    if executable is None:
        return OcrAvailability(False, "Tesseract could not be found.")

    try:
        result = _run([str(executable), *_tessdata_arguments(), "--list-langs"])
    except OSError as failure:
        return OcrAvailability(False, f"Tesseract could not be started ({failure}).")
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        return OcrAvailability(False, f"Tesseract reported an error ({detail or 'unknown'}).")

    listed = (result.stdout or b"").decode("utf-8", "replace").splitlines()
    # The first line is a header ("List of available languages ...").
    languages = tuple(
        line.strip() for line in listed[1:] if line.strip() and " " not in line.strip()
    )
    return OcrAvailability(True, "", str(executable), languages)


def supports(language: Language) -> bool:
    state = availability()
    return state.available and language.tesseract_code in state.languages


def reset_availability_cache() -> None:
    """Forget the cached probe. Used by the tests."""
    availability.cache_clear()


def recognise_page(
    page: pymupdf.Page,
    page_index: int,
    source: Language,
    dpi: float = RECOGNITION_DPI,
) -> PageLayout:
    """Run Tesseract over a page and return the layout it found.

    Raises `OcrUnavailable` when Tesseract or its language data is missing, so
    the caller can tell "we could not look" apart from "we looked and there was
    nothing there".
    """
    state = availability()
    if not state.available:
        raise errors.OcrUnavailable(state.reason)
    if source.tesseract_code not in state.languages:
        raise errors.OcrUnavailable(
            f"the {source.english_name} language data ({source.tesseract_code}.traineddata) "
            "is not installed."
        )

    scale = dpi / 72.0
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, alpha=False
    )
    image = pixmap.tobytes("png")

    command = [
        state.executable,
        "stdin",
        "stdout",
        *_tessdata_arguments(),
        "-l",
        source.tesseract_code,
        # Page segmentation 3: fully automatic, which handles columns.
        "--psm",
        "3",
        "tsv",
    ]
    try:
        result = _run(command, stdin=image)
    except OSError as failure:  # pragma: no cover - runtime guard
        raise errors.OcrUnavailable(str(failure)) from failure
    if result.returncode != 0:  # pragma: no cover - runtime guard
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise errors.OcrUnavailable(f"Tesseract failed: {detail or 'unknown error'}")

    lines = _lines_from_tsv((result.stdout or b"").decode("utf-8", "replace"), scale)
    page_box = page.rect
    return PageLayout(
        page_index=page_index,
        rect=Rect(0.0, 0.0, float(page_box.width), float(page_box.height)),
        blocks=blocks_from_lines(lines),
        was_recognised=True,
    )


# --------------------------------------------------------------------------
# Internals


def _tessdata_arguments() -> list[str]:
    directory = paths.tessdata_directory()
    return ["--tessdata-dir", str(directory)] if directory else []


def _run(command: Sequence[str], stdin: bytes | None = None):
    # CREATE_NO_WINDOW keeps a console flashing up behind the GUI on Windows.
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        list(command),
        input=stdin,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
        creationflags=creation_flags,
        check=False,
    )


def _lines_from_tsv(tsv: str, scale: float) -> list[TextLine]:
    """Turn Tesseract's word-level TSV into text lines in page points."""
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)

    grouped: dict[tuple[int, int, int, int], list[tuple[str, Rect]]] = {}
    order: list[tuple[int, int, int, int]] = []

    for row in reader:
        if row.get("level") != "5":  # word rows only
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            left = float(row["left"])
            top = float(row["top"])
            width = float(row["width"])
            height = float(row["height"])
            key = (
                int(row["page_num"]),
                int(row["block_num"]),
                int(row["par_num"]),
                int(row["line_num"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if confidence < MINIMUM_CONFIDENCE:
            continue

        rect = Rect(left / scale, top / scale, (left + width) / scale, (top + height) / scale)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((text, rect))

    lines: list[TextLine] = []
    for key in order:
        words = grouped[key]
        rect = union_of([box for _, box in words])
        text = " ".join(word for word, _ in words)
        lines.append(
            TextLine(
                text=text,
                rect=rect,
                font_size=max(rect.height * _size_multiplier(text), 1.0),
                # A scan gives no colour information at word level; the
                # renderer samples the page image for OCR'd blocks instead.
                color=0,
            )
        )
    return lines


def _size_multiplier(text: str) -> float:
    """Convert an OCR line-box height into an estimated point size.

    Depends on which letters the line contains: a line of "ANNUAL REPORT"
    covers only the cap height, while "Apply happy" spans from the ascender all
    the way to the descender, and the same box height therefore means two quite
    different point sizes.
    """
    tall = any(character.isupper() or character in _ASCENDERS for character in text)
    deep = any(character in _DESCENDERS for character in text)
    return _SIZE_FULL_SPAN if (tall and deep) else _SIZE_PARTIAL_SPAN
