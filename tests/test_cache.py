"""The sentence cache is what makes repeated page furniture free."""

from __future__ import annotations

from local_pdf_translator.core import languages
from local_pdf_translator.core.cache import TranslationCache
from local_pdf_translator.core.languages import LanguagePair

PAIR = LanguagePair(languages.ENGLISH, languages.GERMAN)
REVERSE = LanguagePair(languages.GERMAN, languages.ENGLISH)


def test_a_stored_translation_comes_back():
    cache = TranslationCache()
    cache.put(PAIR, "hello", "hallo")
    assert cache.get(PAIR, "hello") == "hallo"


def test_a_miss_returns_none():
    assert TranslationCache().get(PAIR, "hello") is None


def test_direction_is_part_of_the_key():
    # "hello"->"hallo" says nothing about translating "hello" the other way.
    cache = TranslationCache()
    cache.put(PAIR, "hello", "hallo")
    assert cache.get(REVERSE, "hello") is None


def test_the_oldest_entry_is_evicted_first():
    cache = TranslationCache(capacity=2)
    cache.put(PAIR, "one", "eins")
    cache.put(PAIR, "two", "zwei")
    cache.put(PAIR, "three", "drei")
    assert cache.get(PAIR, "one") is None
    assert cache.get(PAIR, "two") == "zwei"
    assert cache.get(PAIR, "three") == "drei"


def test_reading_an_entry_keeps_it_alive():
    cache = TranslationCache(capacity=2)
    cache.put(PAIR, "one", "eins")
    cache.put(PAIR, "two", "zwei")
    cache.get(PAIR, "one")  # "one" is now the most recently used
    cache.put(PAIR, "three", "drei")
    assert cache.get(PAIR, "one") == "eins"
    assert cache.get(PAIR, "two") is None


def test_capacity_is_never_exceeded():
    cache = TranslationCache(capacity=10)
    for index in range(50):
        cache.put(PAIR, f"sentence {index}", f"satz {index}")
    assert len(cache) == 10


def test_clear_empties_the_cache():
    cache = TranslationCache()
    cache.put(PAIR, "hello", "hallo")
    cache.clear()
    assert len(cache) == 0
    assert cache.get(PAIR, "hello") is None
