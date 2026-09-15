"""A bounded least-recently-used cache of sentence translations.

Caching at the sentence level rather than the document level is what makes it
worth having: a typical PDF repeats its running header, footer and page
furniture on every page, and those cost nothing after the first occurrence.
"""

from __future__ import annotations

from collections import OrderedDict

from .languages import LanguagePair


class TranslationCache:
    def __init__(self, capacity: int = 4096) -> None:
        self._capacity = max(1, capacity)
        self._storage: OrderedDict[tuple[str, str], str] = OrderedDict()

    def get(self, pair: LanguagePair, sentence: str) -> str | None:
        key = (str(pair), sentence)
        value = self._storage.get(key)
        if value is not None:
            self._storage.move_to_end(key)
        return value

    def put(self, pair: LanguagePair, sentence: str, translation: str) -> None:
        key = (str(pair), sentence)
        self._storage[key] = translation
        self._storage.move_to_end(key)
        while len(self._storage) > self._capacity:
            self._storage.popitem(last=False)

    def clear(self) -> None:
        self._storage.clear()

    def __len__(self) -> int:
        return len(self._storage)
