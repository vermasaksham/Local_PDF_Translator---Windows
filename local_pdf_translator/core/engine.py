"""Translates text using the locally bundled OPUS-MT models.

Nothing here touches the network. The models are CTranslate2 conversions of
Helsinki-NLP's OPUS-MT checkpoints, quantised to int8 so they run at a usable
speed on an ordinary Windows CPU with no GPU.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import errors
from .cache import TranslationCache
from .languages import Language
from .model_catalog import ModelCatalog, ModelDescriptor
from .segmenter import Piece, SentenceSegmenter

#: Called with a fraction in 0..1.
ProgressCallback = Callable[[float], None]


def _default_thread_count() -> int:
    # Leave one core for the UI thread so the window keeps repainting while a
    # long document is translating.
    return max(1, (os.cpu_count() or 2) - 1)


@dataclass
class _LoadedModel:
    """A CTranslate2 translator with its two SentencePiece processors."""

    translator: object
    source_tokenizer: object
    target_tokenizer: object

    def translate(self, sentences: Sequence[str], beam_size: int) -> list[str]:
        encoded = [self.source_tokenizer.encode(text, out_type=str) for text in sentences]
        # Empty token lists make CTranslate2 unhappy and cannot carry meaning
        # anyway, so they are held back and restored afterwards.
        indices = [index for index, tokens in enumerate(encoded) if tokens]
        if not indices:
            return list(sentences)

        results = self.translator.translate_batch(
            [encoded[index] for index in indices],
            beam_size=beam_size,
            max_batch_size=0,
            replace_unknowns=True,
        )

        output = list(sentences)
        for index, result in zip(indices, results, strict=True):
            hypotheses = getattr(result, "hypotheses", None) or [[]]
            output[index] = self.target_tokenizer.decode(hypotheses[0])
        return output


class TranslationEngine:
    """Loads models on demand and keeps them resident.

    Models are shared rather than reconstructed per request: each one is tens
    of megabytes of resident weights, and reloading per translation would
    dominate the runtime of anything short.
    """

    #: Sentences handed to CTranslate2 in one call. Large enough to keep every
    #: core busy, small enough that progress stays responsive and cancellation
    #: is noticed quickly.
    BATCH_SIZE = 24

    def __init__(
        self,
        catalog: ModelCatalog | None = None,
        thread_count: int | None = None,
        cache_capacity: int = 4096,
        beam_size: int = 4,
    ) -> None:
        self.catalog = catalog or ModelCatalog()
        self.thread_count = thread_count or _default_thread_count()
        self.beam_size = beam_size
        self._cache = TranslationCache(cache_capacity)
        self._segmenter = SentenceSegmenter()
        self._models: dict[str, _LoadedModel] = {}
        # Guards both the model dictionary and the CTranslate2 calls: the UI
        # can request a preload while a document translation is in flight.
        self._lock = threading.RLock()

    # -- public API --------------------------------------------------------

    def translate(
        self,
        text: str,
        source: Language,
        target: Language,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> str:
        """Translate a single string, preserving its paragraph structure."""
        result = self.translate_all([text], source, target, progress, cancel)
        return result[0] if result else ""

    def translate_all(
        self,
        texts: Sequence[str],
        source: Language,
        target: Language,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> list[str]:
        """Translate many strings at once.

        Far faster than repeated single calls: every sentence across every
        input is pooled into shared batches, so the decoder stays saturated.
        The result has the same length and order as `texts`.
        """
        if not texts:
            return []
        if source == target:
            return list(texts)

        route = self.catalog.route(source, target)
        if route is None:
            raise errors.NoRouteAvailable(source, target)
        if not route:
            return list(texts)

        current = list(texts)
        for index, descriptor in enumerate(route):
            # Each hop of a pivot occupies its own slice of the progress bar.
            hop_start = index / len(route)
            hop_span = 1.0 / len(route)
            hop_progress = None
            if progress is not None:

                def hop_progress(fraction: float, start=hop_start, span=hop_span) -> None:
                    progress(start + fraction * span)

            current = self._translate_hop(current, descriptor, hop_progress, cancel)
        if progress is not None:
            progress(1.0)
        return current

    def preload(self, source: Language, target: Language) -> None:
        """Load the models a pair needs ahead of time, so the first
        translation is not stalled behind several hundred milliseconds of disk
        and memory work."""
        route = self.catalog.route(source, target)
        if route is None:
            raise errors.NoRouteAvailable(source, target)
        for descriptor in route:
            self._model(descriptor)

    def unload_all(self) -> None:
        """Release loaded models and cached results."""
        with self._lock:
            self._models.clear()
            self._cache.clear()

    def available_targets(self, source: Language) -> list[Language]:
        return self.catalog.reachable_targets(source)

    # -- one hop -----------------------------------------------------------

    def _translate_hop(
        self,
        texts: Sequence[str],
        descriptor: ModelDescriptor,
        progress: ProgressCallback | None,
        cancel: threading.Event | None,
    ) -> list[str]:
        model = self._model(descriptor)
        pair = descriptor.pair

        # Flatten every input into a single pool of sentences so that short
        # inputs do not each pay for an under-filled batch.
        #
        # `translations` is authoritative for this call. The LRU cache only
        # seeds it: relying on the cache for the final substitution would let a
        # document with more unique sentences than the cache capacity evict its
        # own earlier results and silently emit untranslated text.
        segmented: list[list[Piece]] = []
        translations: dict[str, str] = {}
        pending: list[str] = []
        queued: set[str] = set()

        for text in texts:
            pieces = self._segmenter.segment(text, pair.source)
            segmented.append(pieces)
            for piece in pieces:
                if not piece.translatable or piece.text in translations:
                    continue
                cached = self._cache.get(pair, piece.text)
                if cached is not None:
                    translations[piece.text] = cached
                elif piece.text not in queued:
                    # Identical sentences recur constantly across a document
                    # (headers, footers, captions); translate each one once.
                    queued.add(piece.text)
                    pending.append(piece.text)

        for start in range(0, len(pending), self.BATCH_SIZE):
            _raise_if_cancelled(cancel)
            batch = pending[start : start + self.BATCH_SIZE]
            with self._lock:
                try:
                    output = model.translate(batch, self.beam_size)
                except Exception as failure:  # pragma: no cover - runtime guard
                    raise errors.TranslationFailed(str(failure)) from failure
            for sentence, translation in zip(batch, output, strict=True):
                translations[sentence] = translation
                self._cache.put(pair, sentence, translation)
            if progress is not None:
                progress(min(start + len(batch), len(pending)) / len(pending))

        if not pending and progress is not None:
            progress(1.0)

        # Substitute translations back into their original positions.
        return [
            SentenceSegmenter.reassemble(
                [
                    Piece(translations.get(piece.text, piece.text), True)
                    if piece.translatable
                    else piece
                    for piece in pieces
                ]
            )
            for pieces in segmented
        ]

    # -- loading -----------------------------------------------------------

    def _model(self, descriptor: ModelDescriptor) -> _LoadedModel:
        with self._lock:
            existing = self._models.get(descriptor.directory_name)
            if existing is not None:
                return existing

            directory = self.catalog.path(descriptor)
            if not self.catalog.is_installed(descriptor):
                raise errors.ModelMissing(descriptor.directory_name, str(directory))

            model = self._load(descriptor.directory_name, directory)
            self._models[descriptor.directory_name] = model
            return model

    def _load(self, name: str, directory: Path) -> _LoadedModel:
        # Imported here rather than at module scope so that the UI, the tests
        # and the layout code can all be exercised without the native wheels
        # being present.
        try:
            import ctranslate2
            import sentencepiece
        except ImportError as failure:  # pragma: no cover - deployment guard
            raise errors.ModelLoadFailed(
                name,
                f"{failure}. Install the app's dependencies with "
                "pip install -r requirements.txt.",
            ) from failure

        try:
            translator = ctranslate2.Translator(
                str(directory),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=self.thread_count,
            )
            source_tokenizer = sentencepiece.SentencePieceProcessor(
                model_file=str(directory / "source.spm")
            )
            target_tokenizer = sentencepiece.SentencePieceProcessor(
                model_file=str(directory / "target.spm")
            )
        except Exception as failure:  # pragma: no cover - runtime guard
            raise errors.ModelLoadFailed(name, str(failure)) from failure

        return _LoadedModel(translator, source_tokenizer, target_tokenizer)


def _raise_if_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise errors.TranslationCancelled()
