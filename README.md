<div align="center">

<img src="assets/icon.png" width="96" alt="">

# Local PDF Translator

**Translates text and PDF documents entirely on your own PC.**
No API keys, no accounts, no internet connection — ever.

</div>

- **Text tab** — type or paste on the left, read the translation on the right.
- **PDF tab** — drop a PDF on the left, get a translated PDF on the right that
  keeps the original's images, columns, tables, colours and page geometry.

Languages: **English, German, Hindi**, in any direction. Scanned PDFs are read
with OCR first. Adding a language is a two-file change — see
[Adding a language](#adding-a-language).

Requires **Windows 10 (build 1507) or later**, 64-bit. This is the Windows port
of [Local-Pdf-Translator](https://github.com/vermasaksham/Local-Pdf-Translator),
which is the same app for macOS.

---

## Install

Download `LocalPDFTranslator-x.y.z-Setup.exe` from the
[Releases](../../releases) page and run it.

If that page is empty, no release has been published yet — see
[Publishing a release](#publishing-a-release).

The installer is about 370 MB, because the translation models are inside it —
that is the whole point: once installed, the app never needs the network again.
It unpacks to roughly 800 MB. It installs per-user by default, so it does not
require an administrator.

The installer is not code-signed, so Windows SmartScreen will warn that the
publisher is unknown. Choose **More info ▸ Run anyway**.

---

## How it works

```
                     ┌────────────────────────────────┐
   PDF ───────────▶  │  extractor    per-character    │
                     │               boxes, sizes,    │
                     │               colours, weight  │
                     │  ocr          for scanned      │
                     │               pages (Tesseract)│
                     └───────────────┬────────────────┘
                                     ▼
                     ┌────────────────────────────────┐
                     │  analyser     glyphs → lines   │
                     │               lines → blocks   │
                     │               + alignment      │
                     └───────────────┬────────────────┘
                                     ▼
                     ┌────────────────────────────────┐
   text ──────────▶  │  segmenter    blocks →         │
                     │               sentences        │
                     │  engine       CTranslate2 +    │
                     │               OPUS-MT, pooled  │
                     │               and cached       │
                     └───────────────┬────────────────┘
                                     ▼
                     ┌────────────────────────────────┐
                     │  renderer     redact original, │
                     │               fit, redraw      │
                     │  textpainter  vector (Latin)   │
                     │               shaped (Hindi)   │
                     └───────────────┬────────────────┘
                                     ▼
                             translated PDF
```

Four decisions do most of the work:

**Translation happens per paragraph, not per line.** A model handed
`"the quick brown"` and `"fox jumps over"` as separate inputs produces nonsense.
The analyser rebuilds paragraphs from loose glyph boxes first — repairing words
hyphenated across a line break as it goes — and the translation is re-wrapped
into the original's rectangle afterwards.

**The original text is removed, not painted over.** Each translated block is
redacted, which deletes the underlying text objects, so the output's text layer
really is the translation and is searchable. Images, vector art, table rules and
annotations are explicitly left alone. On a *scanned* page the words are pixels
rather than text objects, so there the pixels themselves are cleared and the
background colour is sampled and repainted.

**Text is shrunk before it is allowed to overflow.** German runs 15–30% longer
than English and Hindi longer still. A block first expands downwards into any
whitespace beneath it, then the type is scaled down (to 62% of the original, and
never below 5pt); only if it still will not fit is it allowed to run on. Dropping
a paragraph silently would be far worse than a tight one, and the app reports
how many blocks had to overflow.

**Hindi is shaped, not just drawn.** PDF text drawing has no complex-script
shaping engine: it emits code points in logical order, so `कि` would come out
with its vowel sign on the wrong side of the consonant and conjuncts would never
form. That is wrong text, not merely ugly text. Devanagari is therefore laid out
by Qt's text engine — which shapes complex scripts with its own HarfBuzz — and
placed as a high-resolution image. The trade-off is that Hindi output is a picture of text rather than
selectable text; English and German are written as real, searchable text.

---

## Build it yourself

You need Python 3.11+ and, for the installer,
[Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
git clone <this repo>
cd Local_PDF_Translator---Windows

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python scripts\fetch_models.py       # 1. download + convert models (~10 min, 1.2 GB)
python scripts\bundle_tesseract.py   # 2. copy in Tesseract (optional, for scans)
python scripts\build_exe.py          # 3. build the app
python scripts\build_installer.py    # 4. wrap it in an installer
```

Steps 1 and 2 are one-time. After that, `build_exe.py` alone rebuilds in about a
minute.

### Publishing a release

The installer is built by CI, not committed — it is far too large for a git
repository. To put one on the [Releases](../../releases) page, open the Actions
tab, choose **Build Windows installer**, click **Run workflow**, and set
`release_tag` to the version (`v1.0.0`). The run builds the installer and
publishes it as a release, creating the tag as it goes. Pushing a `v*` tag does
the same thing.

Every other run uploads the installer as a workflow *artifact* instead. That is
fine for testing, but it is a zip rather than an `.exe`, it can only be
downloaded by someone signed in to GitHub, and it is deleted after 90 days — so
it is not a way to hand the app to anyone.

To run from source without building anything:

```powershell
python -m local_pdf_translator
```

Step 2 needs [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
installed, with the German and Hindi language data selected. Without it the app
still builds and runs; it just cannot read scanned pages.

### Checking a build

```powershell
dist\LocalPDFTranslator\LocalPDFTranslator.exe --self-test
```

This verifies the things a compiler cannot: that every model made it into the
bundle, that all six language routes resolve, that a real translation comes back
non-empty, that a Devanagari font is present, and that Qt really shapes it. The
CI workflow runs it on every build.

### Tests

```powershell
python -m pytest
```

186 tests, no models required — the engine is stubbed out. The tests that need
Tesseract skip themselves when it is absent.

---

## Adding a language

Two files:

1. **`local_pdf_translator/core/languages.py`** — add a `Language` with its ISO
   code, its native name, its script, and its Tesseract code. If the script is
   not already known, add it to `Script` with the Windows font files that can
   draw it, and set `needs_shaping` if it is a complex script.
2. **`local_pdf_translator/core/model_catalog.py`** — add a `ModelDescriptor`
   for each direction that Helsinki-NLP publishes a model for.

Nothing else changes. Pairs with no direct model are routed automatically
through the shortest available chain — this is how German↔Hindi already works,
since no `de↔hi` model exists — and the UI, the pipeline and the fetch script
all read from those two lists.

Then re-run `python scripts\fetch_models.py`.

---

## Troubleshooting

**"N translation models are missing"** — `fetch_models.py` was not run, or was
run after `build_exe.py`. Run it, then rebuild.

**Hindi comes out as empty boxes** — no Devanagari font could be loaded. The
app prefers Nirmala UI (on every ordinary Windows 8+ install) and falls back to
the Noto Sans Devanagari it carries in `fonts\`, so this should not happen; if
it does, check that folder survived the install.

**Hindi vowel signs are in the wrong place** — Qt is not shaping complex
scripts, almost always because no Devanagari font could be found. Install
Nirmala UI or Noto Sans Devanagari. The app shows a banner when it detects
this, and `--self-test` checks it explicitly.

**"This PDF has no text layer"** — it is a scan. Tick *Read scanned pages with
OCR*. If the option is greyed out, Tesseract is not bundled in this build.

**Translated text runs over the text below it** — the translation was too long
for its box even at the minimum size. The status line says how many blocks this
happened to. It is a deliberate choice: overflowing is better than silently
losing a paragraph.

**Rotated or vertical text is left untranslated** — text that is not horizontal
is skipped rather than redrawn horizontally over the original, which would be
worse than leaving it.

---

## Privacy

The app makes no network requests. There is no telemetry, no update check, no
model download at runtime, and no account. The only scripts that touch the
network is `fetch_models.py`, and it runs on the build machine, never on a
user's.

Translated PDFs are written to `%LOCALAPPDATA%\LocalPDFTranslator\output` until
you choose where to save them; the uninstaller removes that folder.

---

## Licence

**AGPL-3.0.** Not an arbitrary choice: the app depends on PyMuPDF, which Artifex
dual-licenses as AGPL or commercial, and that propagates to anything distributed
with it. See [`LICENSE`](LICENSE) for the reasoning and the two ways out, and
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) for every dependency.

Models are Helsinki-NLP's OPUS-MT (CC-BY-4.0). CTranslate2 is MIT,
SentencePiece and Tesseract are Apache-2.0, PySide6 is LGPL-3.0.
