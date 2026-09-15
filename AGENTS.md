# AGENTS.md

Orientation for a coding agent picking this project up. Written at the handoff
from Claude Code to OpenAI Codex on 2026-09-15. Everything here was verified
against the repository at commit `c27c6b7`, not recalled from a conversation.

If something below disagrees with the code, the code wins — and fix this file.

---

## 1. Purpose

A Windows desktop application that translates text and PDF documents **entirely
on the user's own machine**. No API keys, no accounts, no network access at
runtime — not for translation, not for telemetry, not for update checks.

Two tabs:

* **Text** — paste on the left, read the translation on the right.
* **PDF** — drop a PDF on the left, get a translated PDF on the right that keeps
  the original's images, columns, tables, colours and page geometry.

Languages: **English, German, Hindi**, in any direction. Scanned PDFs are read
with OCR first.

This repository is the **Windows port**. A separate macOS implementation lives
at `vermasaksham/Local-Pdf-Translator`; the two share design intent but not
code, and neither is a submodule of the other.

---

## 2. Architecture and tech stack

Python 3.11+, PySide6 (Qt) for the interface, PyMuPDF for PDF work, CTranslate2
+ SentencePiece for translation, Tesseract for OCR. Packaged with PyInstaller
(one-folder) and wrapped in an Inno Setup 6 installer.

```
                     ┌────────────────────────────────┐
   PDF ───────────▶  │  extractor    per-character    │
                     │               boxes, sizes,    │
                     │               colours, weight  │
                     │  ocr          scanned pages    │
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

### Layout

| Path | What lives there |
|---|---|
| `local_pdf_translator/core/` | Language definitions, model catalog and routing, sentence segmenter, translation engine, LRU cache, resource paths, error types |
| `local_pdf_translator/pdf/` | Extraction, OCR, layout geometry, block analysis, colour sampling, fonts, renderer, text painters, pipeline driver |
| `local_pdf_translator/ui/` | PySide6 widgets, the two tabs, background workers, theme, app entry point |
| `local_pdf_translator/selftest.py` | `--self-test`: verifies a *packaged* build end to end |
| `scripts/` | Build-machine tooling — model fetch/convert, font fetch, Tesseract bundling, exe build, installer build, icon generation |
| `packaging/` | PyInstaller spec and Inno Setup script |
| `tests/` | pytest suite (194 tests), no model weights required |
| `fonts/` | Bundled Noto Sans Devanagari + its OFL licence |
| `assets/` | Application icon (`.ico` for Windows, `.png` for docs) |

### Translation routing

Four models are bundled: `en↔de` and `en↔hi`. Helsinki-NLP publishes no direct
`de↔hi` model, so `ModelCatalog.route()` does a **breadth-first search** over
installed models and pivots through English automatically. Adding a language
means editing two files (`core/languages.py`, `core/model_catalog.py`) and
nothing else — the UI, pipeline and fetch script all read from those lists.

---

## 3. Source-of-truth rules

* **Version** — `local_pdf_translator/__init__.py` (`__version__`) is the single
  source. `scripts/build_exe.py` and `scripts/build_installer.py` both read it;
  the installer receives it as `/DAppVersion=`. When bumping a release, update
  `pyproject.toml`'s `version` to match by hand — it is **not** derived, and it
  had already drifted once (fixed in this handoff commit).
  `packaging/installer.iss` carries `#define AppVersion "1.0.0"` but it is
  `#ifndef`-guarded and always overridden by the build script; it only applies
  if someone compiles the `.iss` by hand. Leave it alone.
* **Languages and models** — `core/languages.py` and `core/model_catalog.py`.
  Nothing else should hard-code a language code or model name.
* **Bundled resource locations** — `core/paths.py` resolves all three run modes
  (source checkout, PyInstaller build, installed program). No other module
  should check `sys.frozen`.
* **Dependencies** — `requirements.txt` is runtime; `requirements-dev.txt`
  includes it and adds build/test tooling. Pillow is **dev-only** (it is used
  solely by `scripts/make_icon.py`).
* **Lint and format config** — `pyproject.toml` `[tool.ruff]`. The `ignore` list
  is deliberate and each entry is commented; do not prune it without reading why.

---

## 4. Important invariants

Violating any of these will produce output that looks plausible and is wrong.

1. **Translate per paragraph, never per line.** A model handed `"the quick
   brown"` and `"fox jumps over"` as separate inputs produces nonsense. The
   analyser rebuilds paragraphs from loose glyph boxes — repairing words
   hyphenated across a line break — before anything is translated.
2. **Translate per sentence, never per whole paragraph.** OPUS-MT degrades badly
   on multi-sentence input. `SentenceSegmenter` splits and `reassemble()` is
   lossless — `segment()` → `reassemble()` must round-trip exactly, including
   whitespace and untranslatable pieces.
3. **Coordinates are PyMuPDF's, not the PDF format's.** Origin top-left, y grows
   **downwards**. Page rotation is neutralised for the whole run and restored
   afterwards. Converting at the edges only; never mid-heuristic.
4. **Remove original text by redaction, not by painting over it.** Redaction
   deletes the underlying text objects, so the output's text layer really is the
   translation and stays searchable. Images, vector art, table rules,
   annotations and page boxes are explicitly left untouched.
5. **Scanned pages are the exception to (4).** There the words are *pixels*, so
   `PDF_REDACT_IMAGE_PIXELS` is used and the sampled background is repainted.
   Non-scanned pages must use `PDF_REDACT_IMAGE_NONE` or images get destroyed.
6. **Hindi must be shaped, not drawn.** PDF text drawing has no complex-script
   shaping: emitting Devanagari code points in logical order puts vowel signs on
   the wrong side of consonants and never forms conjuncts. That is *wrong text*,
   not ugly text. Hindi goes through Qt's shaper and is placed as an image.
   Pillow's Raqm is **not** an option — it ships only in Pillow's Linux wheels
   and silently is not there on Windows. `shaping_status()` is a *functional*
   check (it measures a conjunct) rather than a build-flag check, for that reason.
7. **Shrink before overflow, never drop.** A block expands into whitespace below,
   then scales down to a floor (62% / 5pt). Only if it still will not fit is it
   allowed to run on, and the run reports how many blocks that happened to.
   Silently losing a paragraph is far worse than a tight one.
8. **The LRU cache is only an optimisation.** `translations` is authoritative
   within a call. If the final substitution read from the cache, a document with
   more unique sentences than the cache capacity would evict its own earlier
   results and silently emit untranslated text. There is a test for this.
9. **Nothing touches the network at runtime.** Only `scripts/fetch_models.py`
   and `scripts/fetch_fonts.py` use the network, and only on a build machine.

### Decoder tunables (`core/engine.py`)

These exist because of a real bug — see §10. Do not revert them casually.

| Constant | Value | Why |
|---|---|---|
| `REPETITION_PENALTY` | `1.1` | CTranslate2 defaults to `1` (off) |
| `NO_REPEAT_NGRAM_SIZE` | `4` | Defaults to `0` (off) |
| `LENGTH_MULTIPLIER` / `LENGTH_SLACK` | `3` / `8` | Cap derived from source length |
| `MINIMUM_DECODING_LENGTH` | `16` | Floor, so short input is not truncated |
| `BUCKET_LENGTH_RATIO` | `2` | Length-homogeneous batches |
| `BATCH_SIZE` | `24` | Sentences per CTranslate2 call |
| `beam_size` (default) | `2` | Was `4`; halves decoding work |

---

## 5. Build, test and lint

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

| Task | Command |
|---|---|
| Tests | `python -m pytest` |
| Lint | `ruff check local_pdf_translator scripts tests` |
| Format check | `ruff format --check local_pdf_translator scripts tests` |
| Format | `ruff format local_pdf_translator scripts tests` |
| Run from source | `python -m local_pdf_translator` |

**Run all three of tests, lint and format check before every commit.** CI runs
exactly these and fails on any of them.

The 194 tests need **no model weights** — the engine is stubbed. Tests that need
Tesseract skip themselves when it is absent. The suite runs on Linux and macOS
as well as Windows, which is how development can proceed without a Windows box.

### Full build (Windows only, needs Inno Setup 6)

```powershell
python scripts\fetch_models.py       # 1. download + convert (~10 min, 1.2 GB) — one-time
python scripts\bundle_tesseract.py   # 2. copy in Tesseract (optional, for scans) — one-time
python scripts\build_exe.py          # 3. build the app (~1 min)
python scripts\build_installer.py    # 4. wrap it in an installer
dist\LocalPDFTranslator\LocalPDFTranslator.exe --self-test
```

`--self-test` verifies what a compile cannot: that every model is in the bundle,
that all six language routes resolve, that a real translation returns non-empty,
that a Devanagari font is present, and that Qt really shapes it. **CI runs it on
every build and the release is gated on it.**

### Environment overrides

`LPT_MODELS_DIR` and `LPT_TESSERACT_EXE` point a source checkout at an
already-installed set of models / Tesseract binary. Useful to avoid the 10-minute
model conversion during development.

---

## 6. Release process

There is **no tag-pushing step**, deliberately. Releases are cut from the GitHub
Actions UI:

1. Bump `__version__` in `local_pdf_translator/__init__.py` **and** `version` in
   `pyproject.toml`. Commit and push.
2. **Actions ▸ Build Windows installer ▸ Run workflow**, with `release_tag` set
   (e.g. `v1.0.3`).
3. The run builds, self-tests, then publishes a GitHub Release and **creates the
   tag itself** via `softprops/action-gh-release`.

Pushing a `v*` tag directly also works and does the same thing, if you have
permission to push tags.

Every other run uploads the installer as a workflow **artifact** instead — fine
for testing, but it is a zip, requires a signed-in GitHub account to download,
and is deleted after 90 days. It is not a way to hand the app to anyone.

**Workflow triggers:** push to `main`, `claude/**` or `codex/**`; any `v*` tag;
any pull request; manual dispatch. See §14 — this list matters after the migration.

---

## 7. Current version and latest release

* **Version in code:** `1.0.2`
* **Latest release:** [`v1.0.2`](https://github.com/vermasaksham/Local_PDF_Translator---Windows/releases/tag/v1.0.2), published 2026-08-29
* **Asset:** `LocalPDFTranslator-1.0.2-Setup.exe`, 386,409,804 bytes (368 MB)
* **SHA-256:** `b16223379d6d0c9663a7e7f601a17693abf66275dd054ab5a9857a71e472f571`
* **Previous:** `v1.0.0` (2026-08-19). **There is no `v1.0.1`** — the version
  went 1.0.0 → 1.0.2 at the user's request. Do not be confused by the gap.

The installer is **not code-signed**, so SmartScreen warns about an unknown
publisher. Signing requires a purchased certificate; nobody has bought one.

---

## 8. Current implementation state

Everything described in §1 is implemented and shipping. Specifically:

* Text tab and PDF tab, both working, with drag-and-drop, progress, cancellation.
* All six language directions, including `de↔hi` via automatic English pivot.
* Layout-preserving PDF output with redaction, shrink-then-reflow fitting,
  alignment detection, list detection, hyphenation repair.
* OCR for scanned pages via bundled Tesseract (`eng`, `deu`, `hin`, `osd`).
* Devanagari shaping through Qt, with a bundled Noto fallback font.
* PyInstaller build, Inno Setup installer, CI, self-test, published releases.
* 194 tests; ruff clean.

**The `v1.0.2` fixes have not been verified against real model weights.** See
§10 and §11 — this is the single most important thing to know before continuing.

---

## 9. Active roadmap

Ordered by what would help most, not by size.

1. **Verify the v1.0.2 decoder fixes on Windows with real models.** Run a
   multi-page, heading-heavy document. Check output quality and wall-clock time.
   This is a prerequisite for trusting anything in §10.
2. **Harden `scripts/ci/setup-tesseract.ps1` against transient download
   failures** — see §10, known CI flake. A retry loop around the single
   `Invoke-WebRequest` at line 32 would do it.
3. **Decide the licence question.** AGPL-3.0 is forced by PyMuPDF; see §12.
4. **Tune threading.** `core/engine.py::_load` uses `inter_threads=1,
   intra_threads=cpu_count-1`. Intra-op scaling is sublinear; on a 4-core machine
   `inter_threads=2, intra_threads=2` often wins. Unbenchmarked — needs a real
   machine and a real document.
5. **Test against real-world PDFs.** Only synthetic documents and one real
   reading-notes PDF have been through the pipeline.
6. **Icon on dark backgrounds.** The mark is near-black on transparent, so it is
   almost invisible on a dark Windows taskbar and in a dark GitHub README.
7. **Code-sign the installer**, if a certificate is ever purchased.

---

## 10. Known bugs and limitations

### Fixed in v1.0.2 but UNVERIFIED against real models

A nine-page reading-notes PDF came back with **40% of its blocks (115 of 260)
decoded into runaway repetition** — `"August 13, 2026"` became 253 tokens of
`13 13 26 26`; headings became `Sach Sach Sach` repeated hundreds of times.

Root cause: OPUS-MT loops on short input, and CTranslate2's defaults do nothing
about it — `repetition_penalty=1`, `no_repeat_ngram_size=0`, and
`max_decoding_length=256` regardless of source length, so a three-token heading
was free to emit 256 tokens. None of the three were being passed.
Commit `a48c35b` sets all three and derives the cap from source length.

The same bug was also the main performance problem: **88% of all decoder work
was spent generating repetition.** Commit `e4659a0` additionally sorts pooled
sentences by length before batching (CTranslate2 pads to the longest in a call
and cannot return until the longest output finishes — simulated 3× saving on
that document) and lowers the default beam from 4 to 2.

> **Both commits were written and tested without model weights.** The sandbox
> they were developed in had no network access to HuggingFace, so no real
> translation was ever run. They are verified against the CTranslate2 API
> contract, the bad output file, and stubbed tests — **not** against real
> output. Treat quality and speed as *claimed, not measured*.
>
> Two specific things to check first: whether any legitimately long sentence is
> now **truncated** by the cap, and whether `beam_size=2` costs noticeable
> quality versus the old `4` (revert with `TranslationEngine(beam_size=4)`).

### Known CI flake

`scripts/ci/setup-tesseract.ps1` downloads `deu.traineddata` / `hin.traineddata`
with a single unretried `Invoke-WebRequest`. On 2026-08-29 one of three
concurrent runs failed with *"An existing connection was forcibly closed by the
remote host"*. **A red Installer job with that message is a flake, not a
regression — re-run it.** Roadmap item 2 fixes it properly.

### Standing limitations

* **The installer is unsigned** — SmartScreen warns about an unknown publisher.
* **Hindi output is an image, not selectable text.** A deliberate trade: correct
  shaping bought at the cost of searchability. English and German are real text.
* **Rotated and vertical text is skipped**, not redrawn horizontally — that
  would be worse than leaving it.
* **Overflow is possible.** When a translation will not fit even at the minimum
  size it runs on, and the status line reports how many blocks that affected.
* **Only synthetic PDFs and one real document** have been tested end to end.
* **Only the four bundled models exist.** `de↔hi` always costs two decoder
  passes because it pivots through English.

---

## 11. Unfinished work — exact state

Nothing is stashed, nothing is uncommitted, nothing is unpushed. The one piece
of genuinely open work:

| Item | Detail |
|---|---|
| **PR** | [#1 — "Offline text and PDF translator for Windows 10 and above"](https://github.com/vermasaksham/Local_PDF_Translator---Windows/pull/1) |
| **State** | **OPEN**, not merged, mergeable |
| **Head** | `c27c6b7` |
| **Base** | `main` |
| **Branch** | `claude/windows-translation-app-1ypiam` — 18 commits ahead of `main`, 0 behind |
| **CI** | Tests and Installer both green on `c27c6b7` (one earlier Installer run on the same commit failed on the Tesseract-download flake described in §10; a later run succeeded and published `v1.0.2`) |
| **Reviews** | None. No review comments, no requested changes. |

**This PR has deliberately not been merged.** It contains the entire project —
`main` holds only an empty initial commit (`9e419a2`) that exists so the branch
had something to open a PR against. Merging is a judgement call for the owner,
not a tidiness exercise. It is safe to merge whenever they want; nothing is
blocking it.

Note the repository's **default branch is currently the feature branch**, not
`main`. If PR #1 is merged, switch the default to `main` and cut subsequent
releases from there, so tags sit on merged history. `v1.0.0` and `v1.0.2` both
currently point at commits on the feature branch.

### Sibling repository

`vermasaksham/Local-Pdf-Translator` (macOS) is clean and fully pushed at
`b11388e` on branches `claude/macos-translation-app-2v7eyp` and
`claude/windows-translation-app-1ypiam` (both the same commit). No outstanding
work there. It is a separate implementation, not a dependency.

---

## 12. Read these first

In this order:

1. **`README.md`** — user-facing overview, the "how it works" diagram, the
   four design decisions that do most of the work, and troubleshooting.
2. **`LICENSE`** — not boilerplate. It explains *why* the project is AGPL-3.0:
   PyMuPDF is dual-licensed AGPL-or-commercial by Artifex, and that propagates
   to anything distributed with it. It sets out the two ways out (buy a
   commercial PyMuPDF licence, or replace it with pypdfium2 and rewrite the
   renderer — which has no redaction API, so this is a large job). **The licence
   choice is an open decision for the owner.** The full AGPL text is vendored
   into this file rather than fetched at build time, because the build machine
   could not reach gnu.org.
3. **`THIRD-PARTY-NOTICES.md`** — every bundled component and its licence. Any
   font added to `fonts/` must be listed here with its licence file alongside.
4. **Module docstrings.** This codebase carries its design rationale in
   docstrings rather than separate ADR files. The ones that matter most:
   `pdf/renderer.py` (in-place editing strategy), `pdf/textpainter.py` (why Qt
   and not Pillow), `pdf/layout.py` (coordinate space), `core/paths.py` (the
   three run modes), `core/engine.py` (decoder guards).

There is no `docs/` directory and no separate ADR log.

---

## 13. Do not modify casually

| Path | Why |
|---|---|
| `LICENSE` | Contains the verbatim AGPL-3.0 text plus the rationale. Do not reformat, re-wrap or "tidy" it. |
| `THIRD-PARTY-NOTICES.md` | Legal obligation, not documentation. Update it when dependencies change. |
| `fonts/` | Bundled Noto Sans Devanagari and its OFL licence. Removing the font breaks Hindi on machines without Nirmala UI (Windows Server images, N editions, stripped installs). `fonts/OFL.txt` must travel with it. |
| `packaging/installer.iss` | Inno Setup script. The `AppVersion` define is a guarded fallback — see §3. |
| `packaging/LocalPDFTranslator.spec` | PyInstaller spec. Note `PYZ(analysis.pure)` — PyInstaller 6 removed `Analysis.zipped_data`. |
| `.github/workflows/build-windows.yml` | The only way an installer gets built. The `Installer` job needs `permissions: contents: write` to publish releases. |
| `local_pdf_translator/__main__.py` | Uses an **absolute** import (`from local_pdf_translator.ui.app import main`). A relative import works from source and dies in the frozen build with `ImportError: attempted relative import with no known parent package`. |
| `assets/icon.ico` | Committed, generated by `scripts/make_icon.py`. Regenerate via the script rather than editing the binary. |
| `models/`, `tesseract/`, `dist/`, `build/` | Gitignored build inputs/outputs. Never commit these — `models/` alone is ~300 MB. |

---

## 14. Migration and backward-compatibility requirements

### For Codex specifically

* **Branch naming affects CI.** The push trigger is
  `branches: [main, "claude/**", "codex/**"]`. `codex/**` was added during this
  handoff so Codex-created branches build. A branch outside those globs will
  **not** trigger a build on push — though opening a PR still triggers CI via
  the `pull_request:` trigger. If you adopt a different prefix, add it to the
  workflow or your pushes will silently produce no installer.
* **The historical branch keeps its name.** `claude/windows-translation-app-1ypiam`
  is the branch PR #1 is built from. Renaming it would close the PR and orphan
  the release tags. Leave it; start new work on new branches.
* **Commit trailers.** Existing history carries `Co-Authored-By: Claude ...` and
  `Claude-Session:` trailers. These are historical provenance — do not rewrite
  history to remove them, and do not copy them onto new commits.

### Product back-compat

* **Installed-app compatibility.** The installer is per-user and writes
  translated output to `%LOCALAPPDATA%\LocalPDFTranslator\output`; the
  uninstaller removes that folder. Changing that path strands users' files.
* **Model directory layout is a contract.** `ModelCatalog.REQUIRED_FILES` is
  `("model.bin", "source.spm", "target.spm")` per model directory, named as in
  `BUNDLED`. `scripts/fetch_models.py` produces that layout and the self-test
  checks it. Changing either side requires changing both plus the spec file.
* **Version numbering.** Semantic-ish; the installer's `AppVersion` and the
  exe's `FileVersion`/`ProductVersion` all derive from `__version__`, which
  `scripts/build_exe.py` pads to four parts. Keep it dotted-numeric.
* **`--self-test` is a release gate**, not a developer convenience. If you add a
  bundled resource, add a check for it in `selftest.py`.
* **Python 3.11+** (`requires-python`, ruff `target-version = "py311"`). The CI
  runner pins 3.11.

---

## 15. Repository facts at handoff

```
commit    c27c6b7  "Release 1.0.2"   (+ this handoff commit)
branch    claude/windows-translation-app-1ypiam  ==  origin (in sync)
main      9e419a2  (empty initial commit only)
tags      v1.0.0, v1.0.2
tests     194 passed
lint      ruff check + ruff format --check clean
worktree  clean; no stashes; nothing unpushed
```
