import pytest

import filter as filter_module
from filter import FilterStage
from stage import stage_config

LABELS = {
    "kurmanji": "kmr_Latn",
    "dimli": "diq_Latn",
    "kirmanjki": "kiu_Latn",
    "sorani": "ckb_Arab",
    "damaged": "hac_Arab",
    "unreadable": "arz_Arab",
    "turkce": "tur_Latn",
}


@pytest.fixture(autouse=True)
def no_glotlid(monkeypatch):
    """`filter.py` calls GlotLID directly; here a text is in the language of its first word."""
    monkeypatch.setattr(filter_module, "detect_lang", lambda text: (LABELS[text.split()[0]], 1.0))


@pytest.fixture
def stage():
    return FilterStage(**stage_config("filter"))


@pytest.fixture
def record(tmp_path):
    def make(word: str, count: int = 50_000) -> dict:
        txt_file = tmp_path / "thesis.txt"
        txt_file.write_text(f"{word} " * count, encoding="utf-8")
        return {"tez_id": "1", "txt_file": str(txt_file), "thesis_word_count": count}

    return make


class TestJudge:
    def test_a_kurmanji_thesis_is_kept_as_kurmanji(self, stage, record):
        assert stage.judge(record("kurmanji")) == ("kmr_Latn", None)

    @pytest.mark.parametrize("word", ["dimli", "kirmanjki"])
    def test_both_zazaki_labels_are_one_language(self, stage, record, word):
        assert stage.judge(record(word)) == ("zza_Latn", None)

    def test_a_sorani_thesis_is_kept_as_sorani(self, stage, record):
        assert stage.judge(record("sorani")) == ("ckb_Arab", None)

    def test_a_thesis_labelled_hac_arab_is_kept_under_that_label(self, stage, record):
        """Six theses in old fonts that extract damaged. Kept apart from clean Sorani."""
        assert stage.judge(record("damaged")) == ("hac_Arab", None)

    def test_an_arabic_script_thesis_under_another_label_is_dropped(self, stage, record):
        assert stage.judge(record("unreadable")) == (None, "text is arz_Arab")

    def test_a_turkish_thesis_is_dropped(self, stage, record):
        assert stage.judge(record("turkce")) == (None, "text is tur_Latn")

    def test_a_short_thesis_is_dropped_without_asking_its_language(self, stage, record):
        assert stage.judge(record("turkce", 10)) == (None, "too short")
