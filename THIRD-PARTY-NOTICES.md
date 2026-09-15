# Third-party components

Everything the installed program contains, and what it is licensed under.
This matters more than usual here: the app ships its dependencies rather than
asking the user to install them, so their terms travel with every copy.

## Libraries

| Component | Licence | Why it is here |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | **AGPL-3.0** or Artifex commercial | Reads per-character geometry out of PDFs, removes the original text with redactions, and draws the replacement. This is the component that forces the project's own licence — see `LICENSE`. |
| [PySide6](https://doc.qt.io/qtforpython/) (Essentials) | LGPL-3.0 | The interface, and the text shaper that makes Hindi output correct. Used unmodified and dynamically linked, which is what the LGPL asks for. The one-folder build keeps the Qt DLLs as separate files so they can be replaced. |
| [HarfBuzz](https://harfbuzz.github.io/) | MIT | Shapes Devanagari. Not a separate dependency — it is built into Qt, which is what lays out and rasterises Hindi text. |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | Runs the translation models on the CPU with int8 quantisation. |
| [SentencePiece](https://github.com/google/sentencepiece) | Apache-2.0 | Tokenises text the way the OPUS-MT models expect. |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) | Apache-2.0 | Reads scanned pages. Bundled as a separate executable, invoked as a subprocess. |
| [Leptonica](http://www.leptonica.org/) | BSD-2-Clause | Image handling inside Tesseract. |

## Models and data

| Component | Licence | Notes |
|---|---|---|
| [Helsinki-NLP OPUS-MT](https://huggingface.co/Helsinki-NLP) models (`en-de`, `de-en`, `en-hi`, `hi-en`) | CC-BY-4.0 | Converted to the CTranslate2 format by `scripts/fetch_models.py`. Attribution belongs to the Language Technology Research Group at the University of Helsinki. |
| Tesseract `eng`, `deu`, `hin`, `osd` traineddata | Apache-2.0 | From the `tessdata` distribution. |

## Fonts

The app prefers the fonts already on the machine — Segoe UI for Latin text and
Nirmala UI for Devanagari, both of which ship with Windows 10 and 11.

| Component | Licence | Notes |
|---|---|---|
| [Noto Sans Devanagari](https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari) | SIL Open Font License 1.1 | Bundled in `fonts/` as a fallback, because a machine with no Devanagari face cannot draw Hindi at all — and Windows Server images, N editions and stripped installs do not always have Nirmala UI. The licence text travels with it in `fonts/OFL.txt`. |

Any font added to `fonts/` must be listed here, with its licence file
alongside it.

## Nothing phones home

The app makes no network requests at all. There is no telemetry, no update
check, no model download at runtime, and no account. The only scripts that use
the network are `scripts/fetch_models.py` and `scripts/fetch_fonts.py`, which
run on the build machine, never on a user's.
