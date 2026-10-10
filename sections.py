"""Stage — Read a thesis's blocks: take the summaries out, keep the rest as text.

One walk over the blocks `extract.py` labelled, and there is nothing else to it:

- a heading starting with `KURTE`/`ÖZET`/`ABSTRACT` opens a summary, and the blocks after
  it are that summary until the next heading;
- a `ÇAVKANÎ` heading opens the bibliography, discarded with everything under it until the
  next heading — reference entries are not Kurmanji prose;
- everything else is text.

A `Section` is a heading and the blocks under it, carrying the `SectionKind` its heading
names. The walk does nothing but cut at headings; what each kind *becomes* is decided
afterwards over the finished list.

Heading detection itself went with `toc.py` (deleted; its `TocParser` is in git history),
because MinerU labels headings for us.

Language is judged twice, each time over a finished piece and never per block (GlotLID,
`langid.py`):

- each section on its way into `text` is labelled, and dropped when the label is not one
  of `SECTION_LANGUAGES`: Kurmanji, Zazaki and Sorani. A section under
  `min_words_for_lang_detect` is too short to label and is kept. No score is read.
- each summary is checked against the language its heading claims. A summary in another
  language becomes `null`. 11 of 1151 were: columns shifted by one (`751821` has its
  Turkish abstract under `KURTE` and its English one under `ÖZET`), or not summaries at
  all (`502779`: a list of tables under `ABSTRACT`).

The Zazaki labels are let through because inside a Kurmanji thesis they are mostly wrong.
Measured on 61,656 sections of 457 theses: in the 407 Kurmanji theses GlotLID labels
319,217 words of sections `kiu_Latn` or `diq_Latn`, and the sampled ones were Kurmanji
title pages and headings in capitals, glossaries, reference lists under a heading other
than `ÇAVKANÎ`, Sorani in Latin letters. What the rule does drop there is about 260,000 of
18,763,980 words: 207,617 Turkish, 9,866 English, and about 43,000 under other labels —
mostly abbreviation lists and tables GlotLID gives odd names (`frp_Latn`, `bew_Latn`).

So this stage does not say which of the three a thesis is in. `filter.py` does: it labels
the whole text once, where GlotLID is reliable, and writes that as `text_lang`.
"""

import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import logs
from blocks import Block, BlockType, load as load_blocks, toc_entries
from langid import detect_lang
from stage import Stage, stage_config


logger = logging.getLogger(__name__)


# The summary languages, in the order the report prints them, and the key each is filed
# under in the manifest's `summaries`. Three languages a thesis is written in, and the two
# every thesis also prints an abstract in.
SUMMARY_LANGUAGES = ("kmr_Latn", "zza_Latn", "ckb_Arab", "tur_Latn", "eng_Latn")

# The GlotLID labels that count as each language. Zazaki comes back under two labels and
# GlotLID does not split the theses between them reliably: of 29 Zazaki theses, 5 get one
# label for the whole text and the other for most of their paragraphs. Sorani in a clean
# Unicode thesis comes back `ckb_Arab` or `hac_Arab` (`878001`: 47% and 48% by section).
LANGUAGE_LABELS = {
    "kmr_Latn": {"kmr_Latn"},
    "zza_Latn": {"kiu_Latn", "diq_Latn"},
    "ckb_Arab": {"ckb_Arab", "hac_Arab", "sdh_Arab"},
    "tur_Latn": {"tur_Latn"},
    "eng_Latn": {"eng_Latn"},
}

# The labels a section may have and stay in `text`: those of the three languages a thesis
# is written in. Which of the three a thesis is in is not decided here — inside a Kurmanji
# thesis a Zazaki label is mostly a Kurmanji heading in capitals, a glossary or a reference
# list — but by `filter.py`, with one label over the whole text.
SECTION_LANGUAGES = (
    LANGUAGE_LABELS["kmr_Latn"] | LANGUAGE_LABELS["zza_Latn"] | LANGUAGE_LABELS["ckb_Arab"]
)

_SUMMARY_WORDS = {
    "kmr_Latn": r"KURTE|PUXTE|PÛXTE|KURTASÎ|KURTASI",
    # Measured over the 30 Zazaki theses: `KILMNUS` 11, `KILMVATE` 4, `KILMÎYE` 2. Not
    # `KILMNUŞTEYÎ`, which is their abbreviations list — `\b` keeps it out, as it does
    # `KURTEBÊJE`.
    "zza_Latn": r"KILMNUS|KILMVATE|KILMÎYE",
    # The four Sorani theses that extract clean: `پوختە` (`878001`, `502253`), `پوختەی
    # لێکۆڵینەوەکە` (`825820`), and `پوخته` with an Arabic heh (`531485`).
    "ckb_Arab": r"پوخت[ەه]ی?",
    "tur_Latn": r"ÖZET|OZET",
    "eng_Latn": r"ABSTRACT|SUMMARY",
}


def _opening_re(alternatives: str) -> re.Pattern:
    """Matches a heading that *starts* with one of these words.

    Only the opening is matched, never the whole heading, because a summary heading hardly
    ever stands alone: MinerU merges the thesis title and the author under it into the same
    block, so `KURTE DAÇEK DI ZARAVAYÊ KURMANCÎYÊ DA Bahattin TAMAN` and `ABSTRACT MASTER'S
    THESIS A STUDY ON …` both have to match.

    `\\b` is what stops it there, and it is load-bearing: without it `KURTE` also matches
    `KURTEBÊJE` and `KURTEPEYV`, the abbreviations lists, which 14 of 22 sampled theses
    print — two thirds of the corpus filing a list of abbreviations as its summary.
    """
    return re.compile(rf"^[\s\d.\-–]*(?:{alternatives})\b", re.IGNORECASE)


# The headings that open a summary, by the language that summary is in.
SUMMARY_OPENINGS = {lang: _opening_re(words) for lang, words in _SUMMARY_WORDS.items()}

# The same words looked for inside a contents block, to tell a summary a thesis never had
# from one whose page would not extract. `\b` on both sides because the entries run
# together there — `KURTE.......VII` — and again to keep `KURTEBÊJE` out.
SUMMARY_IN_CONTENTS = {
    lang: re.compile(rf"\b(?:{words})\b", re.IGNORECASE)
    for lang, words in _SUMMARY_WORDS.items()
}

# The label that opens the keywords closing an abstract. `Miftepeyvên Sereke` is `874610`.
_KEYWORDS_LABEL = (
    r"(?:Peyv[êe]n?\s+(?:Sereke|Bingeh\w*|Kil[îi]t\w*)|B[êe]jey[êe]n\s+Sereke"
    r"|Miftepeyv\w*(?:\s+Sereke)?"
    # Zazaki: `Kilîtçekuyî` in 16 of the 30 theses, the other two once each.
    r"|K[îi]l[îi]t\s?çekuy\w*|Çekuy[êe]\s+(?:Kil[îi]d\w*|Meftey\w*)"
    # Sorani: `وشەی كلیلی`, `وشەی كلییل`, `وشە تێپەڕەكان`, a joiner for the space in `531485`.
    r"|وش[ەه]ی?[\s\u200c]+(?:[كک]لی+ل\w*|تێپ[ەه]ڕ[ەه][كک]ان)"
    r"|Anahtar\s+(?:Kelime|S[öo]zc[üu]k)\w*|Key\s?words?|Key\s+Terms)"
)

# The keywords closing an abstract. They are not part of the summary prose.
#
# Two shapes, both measured on the 1151 summaries of a full run. The label and its colon
# anywhere in a block, because MinerU can merge the keywords into the end of the abstract
# (`931752`: `...hatiye honandin. Peyvên Sereke: ...`). Or the label as a whole block,
# because MinerU can put the colon in the next one (`751831`: `Key Words`, then
# `: Migration, ...`). A bare label inside a longer block is not matched — without the colon
# it is only two words of prose.
#
# It is searched over the joined summary, so `^` and `$` are a block's edges (`MULTILINE`).
KEYWORDS_RE = re.compile(
    rf"\b{_KEYWORDS_LABEL}\s*[:：]|^\s*{_KEYWORDS_LABEL}\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# The bibliography heading: the word, optional numbering, and **at most one more word**.
# `ÇAVKANÎ` and `ÇAVKANÎYÊN DÎJÎTAL` are bibliographies; `Çavkaniyên Sereke yên Tezê` is a
# methodology section written in ordinary prose. Heading length is the only thing that
# separates the two here — the real signal is that a bibliography sits at the *end* of a
# thesis, which this does not look at.
#
# So it is not free: measured over the sampled front matter it also takes `4.Çavkanî`
# (`546095`) and `ÇAVKANIYÊN LÊKOLÎNÊ` (`706158`), both short passages *about* the thesis's
# sources rather than lists of them.
BIBLIOGRAPHY_RE = re.compile(r"^[\s\d.\-–]*ÇAVKAN\w*(\s+\w+)?\s*$", re.IGNORECASE)



def summary_lang(heading: str) -> str | None:
    """The summary language this heading opens, or None if it opens an ordinary one."""
    for lang, pattern in SUMMARY_OPENINGS.items():
        if pattern.match(heading):
            return lang
    return None


@dataclass
class SectionsConfig:
    """The stage's tuning knobs, every one of them read from `config.yml`.

    No field has a default. A default here and a value in `config.yml` are two places to
    change one number, and they drift: `FilterStage` defaulted `min_word_count` to 1000
    while `config.yml` said 100, so running that stage on its own filtered differently from
    running the pipeline. What each knob means is documented beside its value.
    """

    summary_min_words_before_heading: int
    min_words_for_lang_detect: int


class SectionKind(StrEnum):
    """What a heading says the blocks under it are.

    A classification, read straight off the heading as the walk passes it — not a judgment
    made afterwards. Language is such a judgment, which is why it is not a kind: it is
    made over the finished summaries and the finished text, in `ThesisReader.read`.
    """

    TEXT = "text"
    SUMMARY = "summary"
    BIBLIOGRAPHY = "bibliography"


@dataclass
class Section:
    """A heading and the blocks under it, with what kind of thing the heading opened."""

    kind: SectionKind
    heading: str = ""
    # The language a `SUMMARY` heading claims. None for every other kind.
    lang: str | None = None
    paragraphs: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(len(paragraph.split()) for paragraph in self.paragraphs)

    @property
    def block_count(self) -> int:
        return len(self.paragraphs) + bool(self.heading)

    @property
    def text(self) -> str:
        """The heading and the blocks under it, as one text to judge the language of."""
        return "\n\n".join(([self.heading] if self.heading else []) + self.paragraphs)


@dataclass
class Thesis:
    """One thesis after the walk: its summaries, its text, and what was thrown away."""

    summaries: dict[str, str | None]
    paragraphs: list[str]
    # The languages the contents page names a summary in that never reached a column.
    missing: list[str]
    # Blocks dropped as bibliography.
    bibliography: int = 0

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def word_count(self) -> int:
        return sum(len(paragraph.split()) for paragraph in self.paragraphs)


class ThesisReader:
    """Walks a thesis's blocks once, cutting it into sections at the headings.

    The walk itself does one thing: start a new `Section` at every heading, with the kind
    that heading names, and put every other block into whichever section is open. What each
    kind then becomes — a summary column, the `text` column, or nothing — is decided
    afterwards, over a finished list, by `_summary_text` and `_paragraphs`.
    """

    def __init__(self, config: SectionsConfig):
        self._min_words_before_heading = config.summary_min_words_before_heading
        self._min_words_for_lang_detect = config.min_words_for_lang_detect

    def read(self, blocks: list[Block]) -> Thesis:
        sections = self.sections(blocks)
        summary_lang_to_section = {lang: self._first_summary_section(sections, lang) for lang in SUMMARY_LANGUAGES}
        taken = {lang: self._summary_text(s) for lang, s in summary_lang_to_section.items()}
        return Thesis(
            summaries=taken,
            paragraphs=self._paragraphs(sections, summary_lang_to_section.values()),
            missing=self._promised_missing(toc_entries(blocks), taken),
            bibliography=sum(
                section.block_count
                for section in sections
                if section.kind is SectionKind.BIBLIOGRAPHY
            ),
        )

    def _is_lang_valid(self, section: Section) -> bool:
        """Whether a section — its heading and the blocks under it — is in a language
        `text` keeps (`SECTION_LANGUAGES`).

        A section under `min_words_for_lang_detect` is always valid: it is a heading and a
        line, and GlotLID's label for that is noise.
        """
        if len(section.text.split()) < self._min_words_for_lang_detect:
            return True
        return detect_lang(section.text)[0] in SECTION_LANGUAGES

    def sections(self, blocks: list[Block]) -> list[Section]:
        """The thesis cut into sections, in reading order. Nothing else is dropped yet.

        The contents page is skipped: its `index` blocks open no section and belong to none.
        `_promised_missing` reads them instead.
        """
        sections = [Section(kind=SectionKind.TEXT)]
        for block in blocks:
            if block.type is BlockType.INDEX:
                continue
            current = sections[-1]
            if block.is_heading:
                if self._is_title_page_furniture(current):
                    continue

                sections.append(self._create_section(block.text))
            else:
                current.paragraphs.append(block.text)

        return [s for s in sections if s.heading or s.paragraphs]

    @staticmethod
    def _create_section(heading: str) -> Section:
        """The section a heading opens."""
        if BIBLIOGRAPHY_RE.match(heading):
            return Section(kind=SectionKind.BIBLIOGRAPHY, heading=heading)
        lang = summary_lang(heading)
        if lang:
            return Section(kind=SectionKind.SUMMARY, heading=heading, lang=lang)
        return Section(kind=SectionKind.TEXT, heading=heading)

    def _is_title_page_furniture(self, current: Section) -> bool:
        """Whether a heading arriving now is title-page matter rather than the summary's end.

        A thesis prints its title, its author, the university and a page count between a
        summary heading and the abstract itself, and MinerU can mark those as headings of
        their own. Then the first heading after `KURTE` is not the end of the summary.
        `443622` does this for all three languages: `KURTE`, then `WERGER WEK KIRINEKE
        ÇANDÎ` as a second heading, with no words between them. Taking that as the end
        leaves an empty section, `_first_summary_section` picks it, and all three columns come out
        `null`.

        The rule is the summary's length: under `summary_min_words_before_heading` it is still on
        its title page, and a heading is more of that page. Measured on MinerU 4.0.10 over
        four theses (`388894`, `443619`, `443622`, `532507`), the two cases are nowhere
        near each other — a heading that was furniture arrived with **0 words** in the
        summary (4 headings, all in `443622`), and a heading that genuinely ended one
        arrived with **at least 135** (12 headings, 135 to 573). Any threshold between
        those reproduces the same split; 50 is the middle of a very wide gap rather than a
        tuned number. On MinerU 3 the same split was 0 or 2 words against at least 143.

        The rule only matters when MinerU keeps the summary heading apart from the title.
        In the other three theses it merged them into one heading (`KURTE DAÇEK DI ZARAVAYÊ
        KURMANCÎYÊ DA Bahattin TAMAN`), the rule never fired, and `SUMMARY_OPENINGS` did
        the work instead.

        Not a shape test. Judging "has the prose started" by how a block *looks* was tried
        and worked, but it is a second rule to keep true, and the numbers above say a word
        count settles it. Furniture that survives — an author line at the top of a summary —
        is left in: it is a few short lines, and it is easy to drop downstream where the
        summaries are aligned into parallel data.
        """
        return (
            current.kind is SectionKind.SUMMARY
            and current.word_count < self._min_words_before_heading
        )

    def _paragraphs(self, sections: list[Section], taken) -> list[str]:
        """Everything that stays in `text`: headings included.

        Three kinds of section do not: the bibliography, a summary that was taken, and a
        section in another language (`_is_lang_valid`).

        A summary section that was *not* taken stays. A thesis that prints its abstract
        twice has a second `KURTE` section, and that one is body text — dropping it here
        would lose it silently. A second `ÖZET` is body text too, and goes with the other
        sections in another language.

        A summary taken and then dropped for its language does not come back: it is still
        in `taken`. A Turkish abstract under `KURTE` is no more Kurmanji text than it is a
        Kurmanji summary.
        """
        used = {id(section) for section in taken if section is not None}
        paragraphs = []
        for section in sections:
            if section.kind is SectionKind.BIBLIOGRAPHY or id(section) in used:
                continue
            if not self._is_lang_valid(section):
                continue
            if section.heading:
                paragraphs.append(section.heading)
            paragraphs.extend(section.paragraphs)
        return paragraphs

    @staticmethod
    def _first_summary_section(sections: list[Section], lang: str) -> Section | None:
        """The first section whose heading claims a summary in this language.

        A thesis can carry the same summary heading many times over, and the front-matter
        one is always the first: a thesis's own abstract is front matter by definition,
        while the repeats are body text under a heading that happens to share its name.
        `610994` is the case to remember — a study of short stories that prints a `Kurte`
        of each one it analyses:

            section   4  'KURTE'    the abstract (ÖZET at 7, ABSTRACT at 11)
            section  90  'Kurte'    ┐ fourteen per-story summaries,
            …                       ┘ every eighth section, to 197

        Rare — one thesis in the twenty-five whose blocks have been read — but not an
        extraction artefact: MinerU labels all fifteen `title`. The repeats are not taken
        and `_paragraphs` keeps them in `text`, which is what they are.

        Position is the whole rule, and nothing better was needed. Choosing instead by
        proximity to the sibling summaries was measured and is worse: the contents page
        prints KURTE, ÖZET and ABSTRACT on consecutive lines, so "nearest its siblings"
        finds a table of contents, not an abstract. `extract.py` writes that page as `index`
        blocks and the walk skips them — but a rule that is only safe
        because of that is a rule waiting to break.
        """
        return next(
            (s for s in sections if s.kind is SectionKind.SUMMARY and s.lang == lang), None
        )

    @staticmethod
    def _summary_text(section: Section | None) -> str | None:
        """A summary section, cut where its keywords start.

        The keywords close an abstract without being part of it, and 45 of 54 sampled
        summaries have them. The cut falls at the label, not at the block: when MinerU merges
        the keywords into the abstract's last block, the prose before the label is kept.
        Nothing else is trimmed: the title-page blocks a thesis prints above its abstract
        stay where they are.

        A summary that is not in the language its heading claims is None too (GlotLID).
        The heading names the column and the detector only checks it — it never moves a
        summary to another column. Moving would recover about 5 of 1151 and can misfile:
        `751821` has Turkish under `KURTE` and English under both `ÖZET` and `ABSTRACT`, so
        two sections would compete for the English one. The score is not read: a summary is
        hundreds of words of one language, and the 11 mismatches measured were all
        confident (0.93 or more) but one unreadable page.
        """
        if section is None:
            return None
        text = "\n\n".join(section.paragraphs)
        keywords = KEYWORDS_RE.search(text)
        if keywords:
            text = text[: keywords.start()].rstrip()
        if not text:
            return None
        detected = detect_lang(text)[0]
        if detected not in LANGUAGE_LABELS[section.lang]:
            logger.info(f"  {section.lang}: the summary under this heading is {detected}, dropped")
            return None
        return text

    @staticmethod
    def _promised_missing(toc: list[str], summaries: dict[str, str | None]) -> list[str]:
        """The summaries the contents page names that never reached a column.

        Without this a scanned abstract and an abstract the thesis never had look the same
        from here — both are a `null` column. The contents page is the one place a thesis
        *states* it has a KURTE. `447830` and `887531`, the two theses the MinerU switch
        costs, report `['kmr_Latn', 'tur_Latn']` here, so the loss is visible.

        Each entry is searched on its own rather than the contents joined back together:
        the entries carry their leaders and page numbers (`KURTE.iv`, `ÖZET..... IIV`), and
        joining them would let a match straddle two of them.
        """
        return [
            lang
            for lang, pattern in SUMMARY_IN_CONTENTS.items()
            if summaries.get(lang) is None
            and any(pattern.search(entry) for entry in toc)
        ]


@dataclass
class StageStats:
    """What the stage did, totalled over every thesis.

    Printed when the run ends, so tuning a knob in `config.yml` and running again shows
    what moved.
    """

    theses: int = 0
    paragraphs: int = 0
    words: int = 0
    summaries_found: Counter = field(default_factory=Counter)
    summaries_missing: Counter = field(default_factory=Counter)
    summaries_per_thesis: Counter = field(default_factory=Counter)
    bibliography_blocks: int = 0

    def add(self, thesis: Thesis) -> None:
        self.theses += 1
        self.paragraphs += len(thesis.paragraphs)
        self.words += thesis.word_count
        found = [lang for lang in SUMMARY_LANGUAGES if thesis.summaries[lang]]
        self.summaries_found.update(found)
        self.summaries_per_thesis[len(found)] += 1
        self.summaries_missing.update(thesis.missing)
        self.bibliography_blocks += thesis.bibliography

    def report(self) -> str:
        lines = [f"\n{self.theses} theses"]
        lines.append(
            f"\n  text  {self.paragraphs:>9,} paragraphs {self.words:>14,} words"
        )

        lines.append("\n  summaries          found      missing")
        for lang in SUMMARY_LANGUAGES:
            lines.append(
                f"    {lang:<16}{self.summaries_found[lang]:>7}"
                f"{self.summaries_missing[lang]:>13}"
            )
        per_thesis = ", ".join(
            f"{count}: {self.summaries_per_thesis[count]}" for count in range(len(SUMMARY_LANGUAGES) + 1)
        )
        lines.append(f"    theses by summaries found — {per_thesis}")

        lines.append(f"\n  bibliography blocks dropped{self.bibliography_blocks:>9,}")
        return "\n".join(lines)


class SectionsStage(Stage):
    name = "sections"

    def __init__(self, only_theses: list[str] | None = None, **config_kwargs):
        # Every `SectionsConfig` field is settable from config.yml — pipeline.py forwards
        # the stage's extra keys here, so a new knob needs no plumbing beyond the dataclass.
        # `only_theses` is not one of them: it selects what to run, it does not tune it.
        self._only_theses = set(only_theses) if only_theses is not None else set()
        self._config = SectionsConfig(**config_kwargs)
        self._reader = ThesisReader(self._config)

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        if self._only_theses:
            records = [r for r in records if r["tez_id"] in self._only_theses]
            missing = self._only_theses - {r["tez_id"] for r in records}
            if missing:
                print(f"  only_theses: no manifest record for {', '.join(sorted(missing))}")

        print(f"Reading {len(records)} theses")
        output_dir.mkdir(parents=True, exist_ok=True)

        stats = StageStats()

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as manifest_file:
            for number, record in enumerate(records, 1):
                logger.info(f"=== {record['tez_id']} — {record['title']}")
                thesis = self.read_thesis(load_blocks(Path(record["blocks_file"])))
                row = self._write(thesis, record, output_dir)
                manifest_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                stats.add(thesis)
                if not logger.isEnabledFor(logging.INFO):
                    print(f"  [{number}/{len(records)}]", end="\r")

        print(f"\nDone — written to {output_dir}/")
        print(self._config_line())
        print(stats.report())

    def read_thesis(self, blocks: list[Block]) -> Thesis:
        """One thesis's blocks, read. Writes nothing.

        Public because it is the whole stage minus the file handling: everything a caller
        needs to look at a thesis without producing `data/sections/`.
        """
        thesis = self._reader.read(blocks)
        for lang in thesis.missing:
            logger.info(f"  {lang}: the contents page lists this summary, none recovered")
        return thesis

    def _write(self, thesis: Thesis, record: dict, output_dir: Path) -> dict:
        """Write one thesis's text, and return its manifest row."""
        txt_file = output_dir / f"{record['tez_id']}.txt"
        txt_file.write_text(thesis.text, encoding="utf-8")
        return {
            **record,
            "txt_file": str(txt_file),
            "paragraph_count": len(thesis.paragraphs),
            "unrecovered_summaries": thesis.missing,
            "summaries": thesis.summaries,
        }

    def _config_line(self) -> str:
        """The knobs this run used, so a report can be read next to the run that made it."""
        knobs = ", ".join(f"{name}={value}" for name, value in vars(self._config).items())
        return f"  config: {knobs}"

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    logs.configure(debug="--debug" in sys.argv)
    SectionsStage(**stage_config("sections")).run(
        Path("data/extract"), Path("data/sections")
    )
