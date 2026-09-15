"""Model discovery and routing."""

from __future__ import annotations

from local_pdf_translator.core import languages
from local_pdf_translator.core.model_catalog import BUNDLED, ModelCatalog


def test_an_empty_directory_reports_every_model_missing(tmp_path):
    catalog = ModelCatalog(models_directory=tmp_path)
    assert len(catalog.missing_models) == len(BUNDLED)
    assert catalog.route(languages.ENGLISH, languages.GERMAN) is None


def test_a_populated_directory_reports_nothing_missing(installed_catalog):
    assert installed_catalog.missing_models == []


def test_a_direct_pair_routes_through_one_model(installed_catalog):
    route = installed_catalog.route(languages.ENGLISH, languages.GERMAN)
    assert [model.directory_name for model in route] == ["opus-mt-en-de"]


def test_german_to_hindi_pivots_through_english(installed_catalog):
    # Helsinki-NLP publishes no de<->hi model, so this must go the long way.
    route = installed_catalog.route(languages.GERMAN, languages.HINDI)
    assert [model.directory_name for model in route] == ["opus-mt-de-en", "opus-mt-en-hi"]
    assert installed_catalog.pivots(languages.GERMAN, languages.HINDI)


def test_a_direct_pair_does_not_count_as_pivoting(installed_catalog):
    assert not installed_catalog.pivots(languages.ENGLISH, languages.GERMAN)


def test_a_language_routes_to_itself_with_no_models(installed_catalog):
    assert installed_catalog.route(languages.ENGLISH, languages.ENGLISH) == []


def test_a_partially_installed_directory_degrades_rather_than_lying(tmp_path):
    # Only en->de is present. Everything else must report no route, not crash
    # at translation time.
    directory = tmp_path / "opus-mt-en-de"
    directory.mkdir()
    for name in ("model.bin", "source.spm", "target.spm"):
        (directory / name).write_bytes(b"")

    catalog = ModelCatalog(models_directory=tmp_path)
    assert catalog.route(languages.ENGLISH, languages.GERMAN) is not None
    assert catalog.route(languages.ENGLISH, languages.HINDI) is None
    assert catalog.route(languages.GERMAN, languages.HINDI) is None
    assert catalog.reachable_targets(languages.ENGLISH) == [languages.GERMAN]


def test_a_model_missing_one_file_is_not_installed(tmp_path):
    directory = tmp_path / "opus-mt-en-de"
    directory.mkdir()
    # No target.spm: SentencePiece would fail at load, so the catalog must not
    # advertise this as usable.
    (directory / "model.bin").write_bytes(b"")
    (directory / "source.spm").write_bytes(b"")

    catalog = ModelCatalog(models_directory=tmp_path)
    assert catalog.route(languages.ENGLISH, languages.GERMAN) is None


def test_reachable_targets_excludes_the_source(installed_catalog):
    targets = installed_catalog.reachable_targets(languages.ENGLISH)
    assert languages.ENGLISH not in targets
    assert set(targets) == {languages.GERMAN, languages.HINDI}


def test_every_bundled_model_names_a_helsinki_repository():
    for model in BUNDLED:
        assert model.hugging_face_repo.startswith("Helsinki-NLP/")
        # The directory name and the repository must agree, or fetch_models.py
        # and the catalog would disagree about where a model lives.
        assert model.hugging_face_repo.endswith(model.directory_name)


def test_language_lookup_is_case_insensitive():
    assert languages.named("EN") is languages.ENGLISH
    assert languages.named(" de ") is languages.GERMAN
    assert languages.named("zz") is None
