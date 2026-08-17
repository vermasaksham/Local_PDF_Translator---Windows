"""The engine's pooling, de-duplication and substitution logic.

The models themselves are stubbed out: what is under test is everything around
them, which is where the subtle mistakes live — a document that translates its
own header forty times, or one that emits untranslated text because the cache
evicted a sentence mid-run.
"""

from __future__ import annotations

import threading

import pytest

from local_pdf_translator.core import errors, languages
from local_pdf_translator.core.engine import TranslationEngine


class FakeModel:
    """Records every batch it is given and upper-cases what it is asked to translate."""

    def __init__(self, transform=None) -> None:
        self.batches: list[list[str]] = []
        self._transform = transform or (lambda text: text.upper())

    def translate(self, sentences, beam_size):
        self.batches.append(list(sentences))
        return [self._transform(sentence) for sentence in sentences]

    @property
    def translated(self) -> list[str]:
        return [sentence for batch in self.batches for sentence in batch]


@pytest.fixture
def engine(installed_catalog, monkeypatch):
    engine = TranslationEngine(installed_catalog)
    models: dict[str, FakeModel] = {}

    def fake_model(descriptor):
        return models.setdefault(descriptor.directory_name, FakeModel())

    monkeypatch.setattr(engine, "_model", fake_model)
    engine.models = models
    return engine


def english_to_german(engine, texts, **kwargs):
    return engine.translate_all(texts, languages.ENGLISH, languages.GERMAN, **kwargs)


# -- basics ----------------------------------------------------------------


def test_a_single_string_comes_back_translated(engine):
    assert engine.translate("hello there.", languages.ENGLISH, languages.GERMAN) == (
        "HELLO THERE."
    )


def test_output_matches_input_in_length_and_order(engine):
    texts = ["one.", "two.", "three."]
    assert english_to_german(engine, texts) == ["ONE.", "TWO.", "THREE."]


def test_empty_input_returns_empty_output(engine):
    assert english_to_german(engine, []) == []


def test_translating_a_language_into_itself_is_a_no_op(engine):
    texts = ["unchanged."]
    assert engine.translate_all(texts, languages.ENGLISH, languages.ENGLISH) == texts


# -- structure preservation ------------------------------------------------


def test_paragraph_breaks_survive(engine):
    result = engine.translate(
        "First line.\n\nSecond line.", languages.ENGLISH, languages.GERMAN
    )
    assert result == "FIRST LINE.\n\nSECOND LINE."


def test_a_paragraph_is_translated_one_sentence_at_a_time(engine):
    english_to_german(engine, ["One thing. Another thing."])
    model = engine.models["opus-mt-en-de"]
    # OPUS-MT degrades badly on whole paragraphs, so it must see sentences.
    assert model.translated == ["One thing.", "Another thing."]


# -- pooling and de-duplication --------------------------------------------


def test_a_repeated_sentence_is_translated_only_once(engine):
    # A running header appears on every page of a real document.
    english_to_german(engine, ["Confidential."] * 20)
    assert engine.models["opus-mt-en-de"].translated == ["Confidential."]


def test_a_repeated_sentence_is_still_substituted_everywhere(engine):
    result = english_to_german(engine, ["Confidential."] * 20)
    assert result == ["CONFIDENTIAL."] * 20


def test_sentences_are_pooled_across_inputs_into_full_batches(engine):
    # Forty short inputs must not each pay for an under-filled batch.
    english_to_german(engine, [f"Sentence {index}." for index in range(40)])
    batches = engine.models["opus-mt-en-de"].batches
    assert len(batches) == 2
    assert len(batches[0]) == TranslationEngine.BATCH_SIZE


def test_results_survive_a_document_larger_than_the_cache(installed_catalog, monkeypatch):
    """The cache must only ever be an optimisation.

    If the final substitution read from the cache, a document with more unique
    sentences than the cache holds would evict its own earlier results and emit
    untranslated text.
    """
    engine = TranslationEngine(installed_catalog, cache_capacity=4)
    monkeypatch.setattr(engine, "_model", lambda descriptor: FakeModel())

    texts = [f"Unique sentence number {index}." for index in range(60)]
    result = english_to_german(engine, texts)
    assert result == [text.upper() for text in texts]


# -- routing ---------------------------------------------------------------


def test_a_pivot_runs_both_hops(engine):
    engine.translate_all(["Etwas Text."], languages.GERMAN, languages.HINDI)
    assert "opus-mt-de-en" in engine.models
    assert "opus-mt-en-hi" in engine.models


def test_a_missing_route_is_reported_rather_than_guessed(tmp_path):
    from local_pdf_translator.core.model_catalog import ModelCatalog

    engine = TranslationEngine(ModelCatalog(models_directory=tmp_path))
    with pytest.raises(errors.NoRouteAvailable):
        english_to_german(engine, ["anything."])


# -- progress and cancellation ---------------------------------------------


def test_progress_ends_at_one(engine):
    seen: list[float] = []
    english_to_german(engine, [f"Sentence {i}." for i in range(30)], progress=seen.append)
    assert seen and seen[-1] == pytest.approx(1.0)
    assert seen == sorted(seen)


def test_progress_covers_the_whole_range_across_a_pivot(engine):
    seen: list[float] = []
    engine.translate_all(
        [f"Satz {i}." for i in range(30)],
        languages.GERMAN,
        languages.HINDI,
        progress=seen.append,
    )
    # Each hop owns half the bar, so the first hop must not report 1.0.
    assert max(seen[:-1]) <= 1.0
    assert seen[-1] == pytest.approx(1.0)
    assert any(fraction < 0.5 for fraction in seen)


def test_cancelling_raises_rather_than_returning_half_a_document(engine):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(errors.TranslationCancelled):
        english_to_german(engine, [f"Sentence {i}." for i in range(40)], cancel=cancel)


# -- failure ---------------------------------------------------------------


class FakeTokenizer:
    """Mimics SentencePieceProcessor closely enough to check the wiring."""

    def __init__(self) -> None:
        self.encoded: list[str] = []

    def encode(self, text, out_type=None):
        assert out_type is str, "CTranslate2 needs string tokens, not ids"
        self.encoded.append(text)
        return [f"▁{word}" for word in text.split()]

    def decode(self, tokens):
        return " ".join(token.lstrip("▁") for token in tokens)


class FakeResult:
    def __init__(self, hypotheses) -> None:
        self.hypotheses = hypotheses


class FakeTranslator:
    def __init__(self) -> None:
        self.batches: list[list[list[str]]] = []

    def translate_batch(self, batches, **kwargs):
        self.batches.append([list(tokens) for tokens in batches])
        return [FakeResult([[token.upper() for token in tokens]]) for tokens in batches]


def loaded_model():
    from local_pdf_translator.core.engine import _LoadedModel

    return _LoadedModel(FakeTranslator(), FakeTokenizer(), FakeTokenizer())


def test_the_ctranslate2_call_is_wired_up_correctly():
    model = loaded_model()
    assert model.translate(["hello world"], beam_size=4) == ["HELLO WORLD"]
    assert model.translator.batches == [[["▁hello", "▁world"]]]


def test_untokenisable_input_is_passed_through_untouched():
    """CTranslate2 rejects an empty token list.

    Whitespace-only input tokenises to nothing and carries no meaning, so it is
    held back from the batch and put back in place afterwards — rather than
    crashing the whole document.
    """
    model = loaded_model()
    assert model.translate(["   ", "real text"], beam_size=4) == ["   ", "REAL TEXT"]
    # Only the real sentence reached the decoder.
    assert model.translator.batches == [[["▁real", "▁text"]]]


def test_a_wholly_empty_batch_never_reaches_the_decoder():
    model = loaded_model()
    assert model.translate(["", "  "], beam_size=4) == ["", "  "]
    assert model.translator.batches == []


def test_order_is_preserved_when_some_inputs_are_held_back():
    model = loaded_model()
    result = model.translate(["one", "", "two", "   ", "three"], beam_size=4)
    assert result == ["ONE", "", "TWO", "   ", "THREE"]


def test_a_model_failure_is_wrapped_with_context(installed_catalog, monkeypatch):
    class Broken:
        def translate(self, sentences, beam_size):
            raise RuntimeError("CTranslate2 fell over")

    engine = TranslationEngine(installed_catalog)
    monkeypatch.setattr(engine, "_model", lambda descriptor: Broken())

    with pytest.raises(errors.TranslationFailed) as failure:
        english_to_german(engine, ["anything."])
    assert "CTranslate2 fell over" in str(failure.value)
