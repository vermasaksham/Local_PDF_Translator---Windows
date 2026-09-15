"""Knows which models exist, where they live, and how to get from any language
to any other — directly when a model exists, otherwise by pivoting."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import languages, paths
from .languages import Language, LanguagePair

#: Files CTranslate2 and SentencePiece both need before a model can be loaded.
REQUIRED_FILES: tuple[str, ...] = ("model.bin", "source.spm", "target.spm")


@dataclass(frozen=True)
class ModelDescriptor:
    """One OPUS-MT model converted to the CTranslate2 format."""

    #: Directory name under the models root, e.g. `opus-mt-en-de`.
    directory_name: str
    pair: LanguagePair
    #: Upstream Hugging Face repository, recorded so `fetch_models.py` and the
    #: about panel stay in agreement about provenance.
    hugging_face_repo: str


#: The models shipped with the app.
#:
#: Helsinki-NLP publishes direct en<->de and en<->hi models but no de<->hi
#: pair, so German/Hindi is routed through English by `route`. Adding a real
#: de<->hi model later automatically takes precedence, because routing prefers
#: the shortest chain.
BUNDLED: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        "opus-mt-en-de",
        LanguagePair(languages.ENGLISH, languages.GERMAN),
        "Helsinki-NLP/opus-mt-en-de",
    ),
    ModelDescriptor(
        "opus-mt-de-en",
        LanguagePair(languages.GERMAN, languages.ENGLISH),
        "Helsinki-NLP/opus-mt-de-en",
    ),
    ModelDescriptor(
        "opus-mt-en-hi",
        LanguagePair(languages.ENGLISH, languages.HINDI),
        "Helsinki-NLP/opus-mt-en-hi",
    ),
    ModelDescriptor(
        "opus-mt-hi-en",
        LanguagePair(languages.HINDI, languages.ENGLISH),
        "Helsinki-NLP/opus-mt-hi-en",
    ),
)


class ModelCatalog:
    def __init__(
        self,
        models_directory: Path | None = None,
        models: Sequence[ModelDescriptor] = BUNDLED,
    ) -> None:
        self.models_directory = Path(models_directory or paths.models_directory())
        self.models = tuple(models)

    # -- locations ---------------------------------------------------------

    def path(self, model: ModelDescriptor) -> Path:
        return self.models_directory / model.directory_name

    def is_installed(self, model: ModelDescriptor) -> bool:
        """Whether the model's files are actually present on disk."""
        directory = self.path(model)
        return all((directory / name).is_file() for name in REQUIRED_FILES)

    @property
    def missing_models(self) -> list[ModelDescriptor]:
        """Models the catalog advertises but which are absent from disk."""
        return [model for model in self.models if not self.is_installed(model)]

    def model_for(self, pair: LanguagePair) -> ModelDescriptor | None:
        return next((model for model in self.models if model.pair == pair), None)

    # -- routing -----------------------------------------------------------

    def route(self, source: Language, target: Language) -> list[ModelDescriptor] | None:
        """The shortest chain of installed models translating source to target.

        Returns an empty list when the languages are the same (nothing to do),
        and None when no chain exists. Only installed models are considered, so
        a half-populated models directory degrades to a clear error rather than
        a crash at translation time.
        """
        if source == target:
            return []

        edges: dict[Language, list[ModelDescriptor]] = {}
        for model in self.models:
            if self.is_installed(model):
                edges.setdefault(model.pair.source, []).append(model)

        # Breadth-first search keeps the number of hops minimal, which matters:
        # every extra hop compounds translation error.
        visited = {source}
        queue: deque[tuple[Language, list[ModelDescriptor]]] = deque([(source, [])])
        while queue:
            language, path = queue.popleft()
            for model in edges.get(language, ()):
                nxt = model.pair.target
                if nxt in visited:
                    continue
                extended = path + [model]
                if nxt == target:
                    return extended
                visited.add(nxt)
                queue.append((nxt, extended))
        return None

    def reachable_targets(self, source: Language) -> list[Language]:
        """Languages reachable from `source` by any chain of installed models."""
        return [
            language
            for language in languages.ALL
            if language != source and self.route(source, language)
        ]

    def has_route(self, source: Language, target: Language) -> bool:
        return bool(self.route(source, target))

    def pivots(self, source: Language, target: Language) -> bool:
        """True when the pair needs more than one model — slower and lossier,
        which is worth telling the user about."""
        route = self.route(source, target)
        return bool(route) and len(route) > 1
