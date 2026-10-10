import pytest

import sections
from blocks import Block, BlockType, line_text
from sections import (
    SectionsConfig,
    SectionsStage,
    SUMMARY_LANGUAGES,
    Thesis,
    ThesisReader,
)
from stage import stage_config


# Prose has to read as prose: the reader treats short or capitalised blocks under a summary
# heading as the title-page lines a thesis prints there.
PROSE = "ev nivîsa dirêj a kurmancî ye ku ji heşt peyvan zêdetir e"
OTHER_PROSE = "ewa din jî nivîsek dirêj e ku bi heman awayî xuya dike"

# Longer than `summary_min_words_before_heading`, because a real abstract is: the shortest
# heading that genuinely ended a summary in the sample arrived with 143 words above it.
KURMANJI = "kurmanji " * 60
TURKISH = "turkce " * 60
ENGLISH = "english " * 60
ZAZAKI = "zazaki " * 60
SORANI = "sorani " * 60


def fake_detect_lang(text: str) -> tuple[str, float]:
    """Stands in for GlotLID, which is a model download the suite must not make.

    A text is in whichever language's fixture word it has most of — `turkce`, `english`,
    `zazaki`, `sorani` — and Kurmanji when it has none.
    """
    words = text.split()
    prob = 1.0
    counts = {
        "tur_Latn": words.count("turkce"),
        "eng_Latn": words.count("english"),
        "diq_Latn": words.count("zazaki"),
        "ckb_Arab": words.count("sorani"),
    }
    lang = max(counts, key=counts.get)
    return (lang, prob) if counts[lang] else ("kmr_Latn", prob)


def heading(text: str) -> Block:
    """A block MinerU labelled a heading."""
    return Block(text=text, type=BlockType.TITLE, page=0)


def body(text: str) -> Block:
    """A block MinerU labelled prose. One block is one whole paragraph.

    Squeezed the way `extract.py` squeezes it, so a fixture written with loose spacing
    still stands for a block the extractor could actually have produced.
    """
    return Block(text=line_text(text), type=BlockType.TEXT, page=0)


def toc(*headings: str) -> list[Block]:
    """The printed contents page, as `extract.py` writes it: one `index` block per entry."""
    return [Block(f"{h}{'.' * 40}{i + 1}", BlockType.INDEX, 0) for i, h in enumerate(headings)]


@pytest.fixture
def config():
    knobs = stage_config("sections")
    # `only_theses` selects which theses to run, it does not tune anything, so the stage
    # keeps it out of the config too.
    knobs.pop("only_theses", None)
    return SectionsConfig(**knobs)


@pytest.fixture(autouse=True)
def no_glotlid(monkeypatch):
    """`sections.py` calls GlotLID directly; every test here gets the fake instead."""
    monkeypatch.setattr(sections, "detect_lang", fake_detect_lang)


@pytest.fixture
def read(config):
    """Runs the single walk over blocks written inline by a test."""
    reader = ThesisReader(config)

    def run(*blocks: Block, toc: list[Block] | None = None) -> Thesis:
        # The contents page first, where a thesis prints it.
        return reader.read([*(toc or []), *blocks])

    return run


@pytest.fixture
def stage():
    """The whole stage minus the file handling."""
    return SectionsStage(**stage_config("sections"))


class TestText:
    def test_headings_and_prose_both_become_text(self, read):
        thesis = read(heading("DESTPÊK"), body(PROSE), heading("ENCAM"), body(OTHER_PROSE))
        assert thesis.text == f"DESTPÊK\n\n{PROSE}\n\nENCAM\n\n{OTHER_PROSE}"

    def test_blocks_keep_their_order(self, read):
        thesis = read(body(PROSE), heading("DESTPÊK"), body(OTHER_PROSE))
        assert thesis.paragraphs == [PROSE, "DESTPÊK", OTHER_PROSE]

    def test_the_contents_page_never_reaches_the_text(self, read):
        """Its `index` blocks open no section, and the walk skips them."""
        thesis = read(
            heading("DESTPÊK"), body(PROSE), toc=toc("DESTPÊK", "ENCAM")
        )
        assert thesis.paragraphs == ["DESTPÊK", PROSE]
        assert all("....." not in p for p in thesis.paragraphs)

    def test_no_blocks_makes_nothing(self, read):
        thesis = read()
        assert thesis.paragraphs == []
        assert thesis.summaries == {lang: None for lang in SUMMARY_LANGUAGES}

    def test_word_count_counts_the_kept_paragraphs(self, read):
        thesis = read(body("yek du sê"), body("çar pênc"))
        assert thesis.word_count == 5


class TestBibliography:
    @pytest.mark.parametrize("title", ["ÇAVKANÎ", "Çavkanî", "ÇAVKANÎYÊN DÎJÎTAL", "4.Çavkanî"])
    def test_a_bibliography_heading_and_its_entries_are_discarded(self, read, title):
        thesis = read(
            heading("DESTPÊK"), body(PROSE),
            heading(title), body("Baran, B. (2017). Cudatîyên Zimanê Devkî."),
        )
        assert thesis.paragraphs == ["DESTPÊK", PROSE]
        assert thesis.bibliography == 2

    def test_the_next_heading_ends_the_bibliography(self, read):
        thesis = read(
            heading("ÇAVKANÎ"), body("Baran, B. (2017)."),
            heading("PÊVEK"), body(PROSE),
        )
        assert thesis.paragraphs == ["PÊVEK", PROSE]

    def test_a_long_heading_about_sources_is_kept(self, read):
        """`Çavkaniyên Sereke yên Tezê` (782249) introduces prose, it is not a list."""
        thesis = read(heading("Çavkaniyên Sereke yên Tezê"), body(PROSE))
        assert thesis.paragraphs == ["Çavkaniyên Sereke yên Tezê", PROSE]
        assert thesis.bibliography == 0

    def test_a_heading_merely_mentioning_sources_is_kept(self, read):
        thesis = read(heading("GIRÎNGÎ, ARMANC, ÇARÇOVE, RÊBAZ Û ÇAVKANIYÊN MIJARÊ"), body(PROSE))
        assert thesis.bibliography == 0


class TestSummaries:
    def test_takes_each_summary_into_its_own_language(self, read):
        thesis = read(
            heading("KURTE"), body(KURMANJI),
            heading("ÖZET"), body(TURKISH),
            heading("ABSTRACT"), body(ENGLISH),
            heading("DESTPÊK"), body(PROSE),
        )
        assert thesis.summaries == {
            "kmr_Latn": KURMANJI.strip(),
            "zza_Latn": None,
            "ckb_Arab": None,
            "tur_Latn": TURKISH.strip(),
            "eng_Latn": ENGLISH.strip(),
        }
        assert thesis.paragraphs == ["DESTPÊK", PROSE]

    @pytest.mark.parametrize("zazaki_heading", ["KILMNUS", "KILMVATE", "KILMÎYE"])
    def test_takes_a_zazaki_summary(self, read, zazaki_heading):
        thesis = read(heading(zazaki_heading), body(ZAZAKI), heading("VATEYO VERÊN"), body(ZAZAKI))
        assert thesis.summaries["zza_Latn"] == ZAZAKI.strip()
        assert thesis.paragraphs == ["VATEYO VERÊN", ZAZAKI.strip()]

    def test_the_zazaki_abbreviations_list_is_not_a_summary(self, read):
        thesis = read(heading("KILMNUŞTEYÎ"), body(ZAZAKI))
        assert thesis.summaries["zza_Latn"] is None

    def test_the_zazaki_keywords_close_a_zazaki_summary(self, read):
        thesis = read(heading("KILMNUS"), body(ZAZAKI), body("Kilîtçekuyî: Zazakî, Dêrsim"))
        assert thesis.summaries["zza_Latn"] == ZAZAKI.strip()

    @pytest.mark.parametrize("sorani_heading", ["پوختە", "پوختەی لێکۆڵینەوەکە", "پوخته"])
    def test_takes_a_sorani_summary(self, read, sorani_heading):
        thesis = read(heading(sorani_heading), body(SORANI), heading("پێشەكی"), body(SORANI))
        assert thesis.summaries["ckb_Arab"] == SORANI.strip()
        assert thesis.paragraphs == ["پێشەكی", SORANI.strip()]

    @pytest.mark.parametrize("keywords", ["وشەی كلیلی: شێواز", "وشە تێپەڕەكان: شیعرییەت"])
    def test_the_sorani_keywords_close_a_sorani_summary(self, read, keywords):
        thesis = read(heading("پوختە"), body(SORANI), body(keywords))
        assert thesis.summaries["ckb_Arab"] == SORANI.strip()

    def test_a_summary_never_reaches_the_text(self, read):
        thesis = read(heading("KURTE"), body(KURMANJI))
        assert thesis.paragraphs == []

    def test_missing_summaries_are_none(self, read):
        thesis = read(heading("DESTPÊK"), body(PROSE))
        assert thesis.summaries == {lang: None for lang in SUMMARY_LANGUAGES}

    def test_a_summary_runs_until_the_next_heading(self, read):
        thesis = read(
            heading("KURTE"), body(KURMANJI), heading("PÊŞGOTIN"), body(PROSE)
        )
        assert thesis.summaries["kmr_Latn"] == KURMANJI.strip()
        assert thesis.paragraphs == ["PÊŞGOTIN", PROSE]

    @pytest.mark.parametrize(
        "keywords", ["Peyvên Sereke: Cihû", "Anahtar Kelimeler: Kürt", "Keywords: Kurdish"]
    )
    def test_the_keywords_line_closes_a_summary_and_is_thrown_away(self, read, keywords):
        thesis = read(heading("KURTE"), body(KURMANJI), body(keywords))
        assert thesis.summaries["kmr_Latn"] == KURMANJI.strip()
        assert keywords not in thesis.text

    def test_keywords_merged_into_the_abstract_block_are_cut_and_the_prose_kept(self, read):
        """`931752`: MinerU returns the abstract and its keywords as one block."""
        merged = KURMANJI.strip() + " Peyvên Sereke: Helbesta Kurdî, Şêwaz"
        assert read(heading("KURTE"), body(merged)).summaries["kmr_Latn"] == KURMANJI.strip()

    def test_a_keywords_label_split_from_its_colon_still_closes_the_summary(self, read):
        """`751831`: `Key Words` is one block and `: Migration, ...` the next."""
        thesis = read(
            heading("ABSTRACT"), body(ENGLISH), body("Key Words"), body(": Migration, Refugees")
        )
        assert thesis.summaries["eng_Latn"] == ENGLISH.strip()

    def test_miftepeyven_sereke_is_a_keywords_label(self, read):
        """`874610`, whose Turkish abstract followed in the same column."""
        thesis = read(
            heading("KURTE"), body(KURMANJI), body("Miftepeyvên Sereke: Kurmancî"), body(TURKISH)
        )
        assert thesis.summaries["kmr_Latn"] == KURMANJI.strip()

    def test_a_bare_keywords_label_inside_prose_does_not_cut(self, read):
        prose = "The key words " + ENGLISH.strip()
        assert read(heading("ABSTRACT"), body(prose)).summaries["eng_Latn"] == prose

    def test_matches_a_heading_with_the_title_merged_into_it(self, read):
        """MinerU merges the thesis title and author into the summary heading."""
        merged = "KURTE DAÇEK DI ZARAVAYÊ KURMANCÎYÊ DA Bahattin TAMAN"
        assert read(heading(merged), body(KURMANJI)).summaries["kmr_Latn"] == KURMANJI.strip()

    def test_matches_an_english_heading_merged_with_the_title(self, read):
        merged = "ABSTRACT MASTER'S THESIS A STUDY ON KURDISH NOVELS"
        assert read(heading(merged), body(ENGLISH)).summaries["eng_Latn"] == ENGLISH.strip()

    @pytest.mark.parametrize("abbreviations", ["KURTEBÊJE", "KURTEPEYV"])
    def test_does_not_match_the_abbreviations_heading(self, read, abbreviations):
        """14 of 22 sampled theses print one. Without `\\b` each is a false KURTE."""
        thesis = read(heading(abbreviations), body(KURMANJI))
        assert thesis.summaries["kmr_Latn"] is None
        assert thesis.paragraphs == [abbreviations, KURMANJI.strip()]

    def test_keeps_the_first_of_two_summaries_in_a_language(self, read):
        """A thesis may reprint its abstract; the second is ordinary text."""
        thesis = read(
            heading("KURTE"), body(KURMANJI),
            heading("KURTE"), body("kurmanji din " * 30),
        )
        assert thesis.summaries["kmr_Latn"] == KURMANJI.strip()
        assert thesis.paragraphs[0] == "KURTE"

    def test_the_title_page_blocks_stay_in_the_summary(self, read):
        """Deliberate. They are a few short lines and easy to drop where the summaries are
        aligned into parallel data; trimming them here needed a second rule about shape."""
        thesis = read(
            heading("ABSTRACT"),
            body("Master Thesis"),
            body("Ali ONAY"),
            body(ENGLISH),
        )
        assert thesis.summaries["eng_Latn"].startswith("Master Thesis")
        assert ENGLISH.strip() in thesis.summaries["eng_Latn"]

    def test_a_heading_among_the_title_page_blocks_does_not_end_the_summary(self, read):
        """MinerU marks the thesis title under `ABSTRACT` as a heading of its own."""
        thesis = read(
            heading("ABSTRACT"),
            body("Master Thesis"),
            heading("Listening Book Recommendation for Kurmanji Kurdish"),
            body("Ali ONAY"),
            body(ENGLISH),
        )
        assert ENGLISH.strip() in thesis.summaries["eng_Latn"]
        assert thesis.paragraphs == []

    def test_a_summary_heading_with_nothing_after_it_is_none(self, read):
        thesis = read(body(PROSE), heading("KURTE"))
        assert thesis.summaries["kmr_Latn"] is None

    def test_a_heading_arriving_before_the_summary_is_long_enough_is_dropped(self, read):
        """The whole rule, stated once: under the knob, a heading is more title page.

        Dropped rather than kept — it is the thesis title, and it is already the `title`
        column of the dataset.
        """
        thesis = read(
            heading("ABSTRACT"), body("Master Thesis"),
            heading("A Study On Kurdish Novels"),
            body(ENGLISH),
        )
        assert "A Study On Kurdish Novels" not in thesis.summaries["eng_Latn"]
        assert "A Study On Kurdish Novels" not in thesis.text

    def test_a_short_summary_swallows_the_section_after_it(self, read):
        """The cost of the knob, written down.

        An abstract shorter than the threshold is still "on its title page" as far as this
        rule can tell, so the next heading is dropped and its text joins the summary. The
        sample has no abstract this short — the smallest heading that genuinely ended one
        arrived with 143 words above it — but nothing guarantees that across the corpus.
        """
        thesis = read(
            heading("KURTE"), body("kurmanji " * 10),
            heading("PÊŞGOTIN"), body(PROSE),
        )
        assert PROSE in thesis.summaries["kmr_Latn"]
        assert thesis.paragraphs == []


class TestLanguage:
    def test_a_summary_in_another_language_is_dropped(self, read):
        """`476000`: an English abstract under `KURTE`."""
        thesis = read(heading("KURTE"), body(ENGLISH), heading("DESTPÊK"), body(PROSE))
        assert thesis.summaries["kmr_Latn"] is None

    def test_a_dropped_summary_does_not_go_back_into_the_text(self, read):
        thesis = read(heading("KURTE"), body(ENGLISH), heading("DESTPÊK"), body(PROSE))
        assert thesis.paragraphs == ["DESTPÊK", PROSE]

    def test_a_summary_is_never_moved_to_the_column_of_its_language(self, read):
        """`751821`: Turkish under `KURTE`, English under `ÖZET`. Both go."""
        thesis = read(
            heading("KURTE"), body(TURKISH),
            heading("ÖZET"), body(ENGLISH),
            heading("ABSTRACT"), body(ENGLISH),
        )
        assert thesis.summaries == {
            "kmr_Latn": None,
            "zza_Latn": None,
            "ckb_Arab": None,
            "tur_Latn": None,
            "eng_Latn": ENGLISH.strip(),
        }

    def test_a_dropped_summary_the_contents_named_is_reported_missing(self, read):
        thesis = read(
            heading("KURTE"), body(TURKISH),
            heading("DESTPÊK"), body(PROSE),
            toc=toc("KURTE", "DESTPÊK"),
        )
        assert thesis.missing == ["kmr_Latn"]

    def test_a_summary_in_its_own_language_is_kept(self, read):
        assert read(heading("ÖZET"), body(TURKISH)).summaries["tur_Latn"] == TURKISH.strip()


class TestSectionLanguage:
    def test_a_turkish_section_is_dropped_and_its_neighbours_kept(self, read):
        thesis = read(
            heading("PÊŞGOTIN"), body(PROSE),
            heading("TEZ ONAYI"), body(TURKISH),
            heading("DESTPÊK"), body(OTHER_PROSE),
        )
        assert thesis.paragraphs == ["PÊŞGOTIN", PROSE, "DESTPÊK", OTHER_PROSE]

    def test_an_english_section_is_dropped(self, read):
        thesis = read(heading("DESTPÊK"), body(PROSE), heading("APPENDIX"), body(ENGLISH))
        assert thesis.paragraphs == ["DESTPÊK", PROSE]

    @pytest.mark.parametrize("kurdish", [ZAZAKI, SORANI])
    def test_a_section_labelled_zazaki_or_sorani_is_kept(self, read, kurdish):
        """Inside a Kurmanji thesis a Zazaki label is mostly a Kurmanji heading or glossary."""
        thesis = read(heading("DESTPÊK"), body(PROSE), heading("FERHENG"), body(kurdish))
        assert thesis.paragraphs == ["DESTPÊK", PROSE, "FERHENG", kurdish.strip()]

    def test_the_blocks_before_the_first_heading_are_a_section_too(self, read):
        thesis = read(body(TURKISH), heading("DESTPÊK"), body(PROSE))
        assert thesis.paragraphs == ["DESTPÊK", PROSE]

    def test_a_second_summary_in_turkish_is_dropped_too(self, read):
        thesis = read(
            heading("ÖZET"), body(TURKISH),
            heading("DESTPÊK"), body(PROSE),
            heading("ÖZET"), body(TURKISH * 2),
        )
        assert thesis.summaries["tur_Latn"] == TURKISH.strip()
        assert thesis.paragraphs == ["DESTPÊK", PROSE]

    def test_a_section_too_short_to_label_is_kept(self, read):
        """A heading and a line: GlotLID's label for that is noise."""
        short = "turkce " * 10
        thesis = read(heading("T.C."), body(short), heading("DESTPÊK"), body(PROSE))
        assert thesis.paragraphs == ["T.C.", short.strip(), "DESTPÊK", PROSE]

    def test_a_turkish_thesis_has_no_text(self, read):
        assert read(heading("GİRİŞ"), body(TURKISH)).paragraphs == []

    def test_a_zazaki_thesis_keeps_its_text(self, read):
        """`filter` names its language, with one label over the whole text."""
        thesis = read(heading("DESTPÊK"), body(ZAZAKI))
        assert thesis.paragraphs == ["DESTPÊK", ZAZAKI.strip()]


class TestPromisedMissing:
    def test_the_contents_reports_a_summary_it_named_that_was_lost(self, read):
        """A thesis whose summary pages are scanned images extracts them as nothing.

        The contents entry is the only surviving evidence the summary was ever there.
        """
        thesis = read(
            heading("DESTPÊK"), body(PROSE),
            toc=toc("KURTE", "ÖZET", "ABSTRACT", "DESTPÊK"),
        )
        assert sorted(thesis.missing) == ["eng_Latn", "kmr_Latn", "tur_Latn"]

    def test_a_summary_the_contents_never_named_is_not_reported_missing(self, read):
        """Most theses print no Kurmanji abstract at all; that is not a lost page."""
        thesis = read(
            heading("DESTPÊK"), body(PROSE), toc=toc("ÖZET", "ABSTRACT", "DESTPÊK")
        )
        assert sorted(thesis.missing) == ["eng_Latn", "tur_Latn"]

    def test_the_abbreviations_list_is_not_a_promise_of_a_kurte(self, read):
        thesis = read(
            heading("DESTPÊK"), body(PROSE), toc=toc("KURTEBÊJE", "DESTPÊK")
        )
        assert thesis.missing == []

    def test_a_recovered_summary_is_not_reported_missing(self, read):
        thesis = read(
            heading("KURTE"), body(KURMANJI),
            heading("DESTPÊK"), body(PROSE),
            toc=toc("KURTE", "DESTPÊK"),
        )
        assert thesis.missing == []


class TestEndToEnd:
    def test_the_summaries_leave_the_text(self, stage):
        thesis = stage.read_thesis([
            *toc("KURTE", "ÖZET", "ABSTRACT", "DESTPÊK"),
            heading("ZANÎNGEHA MARDÎN ARTUKLUYÊ"),
            heading("KURTE"), body(KURMANJI), body("Peyvên Sereke: Cihû"),
            heading("ÖZET"), body(TURKISH),
            heading("ABSTRACT"), body(ENGLISH),
            heading("DESTPÊK"), body(PROSE),
            heading("ÇAVKANÎ"), body("Baran, B. (2017). Cudatîyên Zimanê Devkî."),
        ])
        assert thesis.summaries["kmr_Latn"] == KURMANJI.strip()
        assert thesis.summaries["tur_Latn"] == TURKISH.strip()
        assert thesis.summaries["eng_Latn"] == ENGLISH.strip()
        assert thesis.missing == []
        assert thesis.summaries["zza_Latn"] is None
        assert thesis.summaries["ckb_Arab"] is None
        for lang in ("kmr_Latn", "tur_Latn", "eng_Latn"):
            assert thesis.summaries[lang] not in thesis.text
        assert "Baran, B." not in thesis.text
        assert thesis.paragraphs == ["ZANÎNGEHA MARDÎN ARTUKLUYÊ", "DESTPÊK", PROSE]

