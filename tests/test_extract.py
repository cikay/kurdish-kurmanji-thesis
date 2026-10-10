"""What the extract stage makes of MinerU's output.

MinerU itself is never run here: it loads models and reads under a page a second, and the
suite runs offline in well under a second. What is tested is the part this repo owns —
which of MinerU's block types are kept and with what type, how a block's spans are joined,
and which blocks are the contents page.

The fixtures are MinerU's real block objects, `docvortex` models, built by `block()` and
`pages()`. `docvortex` is pydantic and nothing else, so importing it costs nothing and
imports no torch — and a fixture that the real parser could not produce fails to build.
"""
import json
import os
import unicodedata

import pytest
from docvortex.schema import (
    DocTitleBlock,
    EquationBlock,
    EquationInlineSpan,
    ImageBlock,
    ImageBodyBlock,
    IndexBlock,
    ListBlock,
    PageAuxTextBlock,
    PageFootnoteBlock,
    PageInfo,
    ParagraphTitleBlock,
    RefTextBlock,
    TableBlock,
    TableBodyBlock,
    TextBlock,
    TextSpan,
)

from blocks import Block, BlockType, dump, line_text, load, toc_entries
from extract import BLOCK_TYPES, ExtractStage, MinerUExtractor, blocks_path, manifest_row


def span(text: str) -> TextSpan:
    return TextSpan(type="text", content=text)


def block(kind: str, *texts: str, level: int | None = None):
    """One MinerU block of `kind`, holding `texts`.

    For most kinds the texts are the block's spans. For `index` they are its entries: a
    contents page nests a block per printed line, which is where the entries come from.

    A heading's `level` is required by MinerU's model and starts at 2 for a section
    heading, 1 being the document's own title. Nothing in this stage reads it.
    """
    spans = [span(text) for text in texts]
    if kind == "title":
        return ParagraphTitleBlock(type="paragraph_title", level=level or 2, content=spans)
    if kind == "doc_title":
        return DocTitleBlock(type="doc_title", level=level or 1, content=spans)
    if kind == "text":
        return TextBlock(type="text", content=spans)
    if kind == "ref_text":
        return RefTextBlock(type="ref_text", content=spans)
    if kind == "list":
        return ListBlock(
            type="list", content=[TextBlock(type="text", content=[s]) for s in spans]
        )
    if kind == "index":
        return IndexBlock(
            type="index", content=[TextBlock(type="text", content=[s]) for s in spans]
        )
    if kind in ("page_number", "header", "footer", "aside_text"):
        return PageAuxTextBlock(type=kind, content=spans)
    if kind == "page_footnote":
        return PageFootnoteBlock(type="page_footnote", content=spans)
    if kind == "equation":
        return EquationBlock(type="equation", content=texts[0] if texts else "")
    if kind == "image":
        # An image nests exactly one body block, which is where its file would be.
        return ImageBlock(
            type="image", content=[ImageBodyBlock(type="image_body", content="")]
        )
    if kind == "table":
        return TableBlock(
            type="table", content=[TableBodyBlock(type="table_body", content="<table></table>")]
        )
    raise ValueError(f"no fixture for block type {kind!r}")


def pages(*page_blocks: list) -> list[PageInfo]:
    """MinerU's pages, one block list each, numbered from 0 as it numbers them.

    Every top-level block is given its reading-order `index`, which MinerU's own page
    model requires. Nothing in this stage reads it — position in the list is what counts.
    """
    numbered = []
    position = 0
    for page_idx, blocks in enumerate(page_blocks):
        indexed = []
        for block in blocks:
            indexed.append(_indexed(block, position))
            position += 1
        numbered.append(PageInfo(page_idx=page_idx, blocks=indexed))
    return numbered


def _indexed(block, position: int):
    """One block at its reading-order position.

    An image's or table's nested body block has to carry the same index as its parent,
    which MinerU's model checks, so it is stamped here too.
    """
    content = getattr(block, "content", None)
    if not isinstance(content, list):
        return block.model_copy(update={"index": position})
    nested = [
        item.model_copy(update={"index": position})
        if str(getattr(item, "type", "")).endswith("_body")
        else item
        for item in content
    ]
    return block.model_copy(update={"index": position, "content": nested})


# A thesis's worth of body text after the front matter. The contents region is the first
# quarter of the blocks, so a fixture needs a body behind its contents page for the page to
# sit where a real one does.
FILLER = [block("text", f"ev paragrafeke laşê tezê ye {n}") for n in range(20)]


def body_of(found: list[Block]) -> list[Block]:
    """Every block but the contents page's."""
    return [b for b in found if b.type is not BlockType.INDEX]


@pytest.fixture
def extractor():
    return MinerUExtractor(tier="basic", ocr_mode="auto", processing_window_size=16)


class TestLineText:
    def test_squeezes_the_double_spaces_extraction_leaves(self):
        assert line_text("Bu  tezin  kabulü") == "Bu tezin kabulü"

    def test_strips_the_surrounding_space(self):
        assert line_text("   ev nivîs e   ") == "ev nivîs e"

    def test_keeps_hyphens_as_written(self):
        """Healing these was measured at 77 fires and 77 false positives."""
        assert line_text("Kurdistan- A Selection") == "Kurdistan- A Selection"

    def test_empty_line(self):
        assert line_text("") == ""


class TestBlockTypes:
    def test_both_of_mineru_s_title_types_become_a_heading(self, extractor):
        """MinerU is not consistent about which it uses: in `532507` `ÖZET` came back a
        `doc_title` and `KURTE` a `paragraph_title`, two pages apart. What opens a section
        here is being a heading at all."""
        found = extractor._blocks(pages([
            block("title", "KURTE", level=2), block("doc_title", "ÖZET"),
        ]))
        assert body_of(found) == [
            Block(text="KURTE", type=BlockType.TITLE, page=0),
            Block(text="ÖZET", type=BlockType.TITLE, page=0),
        ]

    def test_text_and_list_keep_their_mineru_type(self, extractor):
        found = extractor._blocks(pages([block("text", "yek"), block("list", "sê")]))
        assert [b.type for b in body_of(found)] == [BlockType.TEXT, BlockType.LIST]
        assert [b.text for b in body_of(found)] == ["yek", "sê"]

    def test_a_bibliography_entry_stays_text(self, extractor):
        """MinerU 4 labels reference lines `ref_text`. They stay text so that
        `sections.py` keeps deciding what a bibliography is by its `ÇAVKANÎ` heading."""
        found = extractor._blocks(pages([block("ref_text", "Baran, B. (2017). Cudatî.")]))
        assert body_of(found) == [
            Block(text="Baran, B. (2017). Cudatî.", type=BlockType.TEXT, page=0)
        ]

    def test_the_contents_page_becomes_index_blocks(self, extractor):
        """Kept, not dropped: it is what says which summaries a thesis claims to have."""
        found = extractor._blocks(pages([block("index", "KURTE .... VII")]))
        assert found == [Block(text="KURTE .... VII", type=BlockType.INDEX, page=0)]
        assert toc_entries(found) == ["KURTE .... VII"]
        assert body_of(found) == []

    def test_the_contents_page_keeps_one_block_per_entry(self, extractor):
        """Run together, the entries weld and cannot be read apart again."""
        found = extractor._blocks(pages([
            block("index", "KURTE .... III", "ÖZET ..... IIV", "ABSTRACT ... V")
        ]))
        assert toc_entries(found) == ["KURTE .... III", "ÖZET ..... IIV", "ABSTRACT ... V"]

    def test_contents_pages_across_pages_all_land_in_the_toc(self, extractor):
        found = extractor._blocks(pages(
            [block("index", "KURTE .... III")], [block("index", "DESTPÊK .... 1")], FILLER
        ))
        assert toc_entries(found) == ["KURTE .... III", "DESTPÊK .... 1"]

    def test_figures_tables_and_formulas_are_dropped(self, extractor):
        found = extractor._blocks(pages([
            block("image"), block("table"), block("equation", "x^2"),
        ]))
        assert body_of(found) == []

    def test_page_furniture_is_dropped(self, extractor):
        """MinerU 3 kept these out of the way in `discarded_blocks`. MinerU 4 has no such
        list — they arrive among the blocks, and `BLOCK_TYPES` is what leaves them out."""
        found = extractor._blocks(pages([
            block("page_number", "VII"),
            block("header", "DAÇEK DI ZARAVAYÊ KURMANCÎ DA"),
            block("footer", "Mardin Artuklu"),
            block("aside_text", "Şekl 1"),
            block("page_footnote", "1 Bnr. Cizîrî, r. 12"),
            block("text", "prose"),
        ]))
        assert [b.text for b in body_of(found)] == ["prose"]

    def test_an_empty_block_is_dropped(self, extractor):
        """Image-only pages come back as blocks with no text spans at all."""
        assert body_of(extractor._blocks(pages([block("text"), block("text", "   ")]))) == []

    def test_blocks_keep_their_page(self, extractor):
        found = extractor._blocks(pages([block("text", "yek")], [block("text", "du")]))
        assert [b.page for b in body_of(found)] == [0, 1]

    def test_blocks_stay_in_reading_order(self, extractor):
        found = extractor._blocks(pages([
            block("title", "KURTE"), block("text", "prose"), block("title", "ÖZET"),
        ]))
        assert [b.text for b in body_of(found)] == ["KURTE", "prose", "ÖZET"]


class TestBlockText:
    def test_a_paragraph_comes_back_as_one_span(self, extractor):
        """MinerU 4 joins the lines a paragraph was wrapped across before this stage."""
        found = extractor._blocks(pages([
            block("text", "ev nivîsa dirêj a kurmancî ye ku ji heşt peyvan zêdetir e")
        ]))
        assert body_of(found)[0].text == "ev nivîsa dirêj a kurmancî ye ku ji heşt peyvan zêdetir e"

    def test_joins_the_spans_a_block_was_split_across(self, extractor):
        """A span is a piece of a line, not a line: a style change can fall inside a word,
        so there is nothing between them."""
        found = extractor._blocks(pages([block("text", "Kur", "mancî")]))
        assert body_of(found)[0].text == "Kurmancî"

    def test_ignores_a_non_text_span(self, extractor):
        """An inline formula's LaTeX is not Kurmanji and does not belong in the prose."""
        block_with_formula = TextBlock(
            type="text",
            content=[span("wekhevî"), EquationInlineSpan(type="equation_inline", content="x^2")],
        )
        found = extractor._blocks(pages([block_with_formula]))
        assert body_of(found)[0].text == "wekhevî"

    def test_keeps_a_hyphen_as_written(self, extractor):
        found = extractor._blocks(pages([block("text", "Kurdistan- A Selection")]))
        assert body_of(found)[0].text == "Kurdistan- A Selection"


class TestBlocksFile:
    def test_round_trips(self, tmp_path):
        written = [
            Block("KURTE .... III", BlockType.INDEX, 3),
            Block("KURTE", BlockType.TITLE, 6),
            Block("prose", BlockType.TEXT, 6),
        ]
        path = tmp_path / "1.blocks.json"
        dump(written, path)
        assert load(path) == written

    def test_is_written_as_a_readable_json_list(self, tmp_path):
        path = tmp_path / "1.blocks.json"
        dump([Block("KURTE.iv", BlockType.INDEX, 3), Block("KURTE", BlockType.TITLE, 6)], path)
        assert json.loads(path.read_text(encoding="utf-8")) == [
            {"text": "KURTE.iv", "type": "index", "page": 3},
            {"text": "KURTE", "type": "title", "page": 6},
        ]

    def test_every_written_type_round_trips(self, tmp_path):
        written = [
            Block("ÖZET .... IV", BlockType.INDEX, 3),
            Block("KURTE", BlockType.TITLE, 6), Block("yek", BlockType.TEXT, 6),
            Block("du", BlockType.ABSTRACT, 6), Block("sê", BlockType.LIST, 7),
        ]
        path = tmp_path / "1.blocks.json"
        dump(written, path)
        assert load(path) == written

    def test_toc_entries_are_the_index_blocks_in_order(self):
        found = [
            Block("KURTE .... III", BlockType.INDEX, 3),
            Block("KURTE", BlockType.TITLE, 6),
            Block("ÖZET .... IV", BlockType.INDEX, 3),
        ]
        assert toc_entries(found) == ["KURTE .... III", "ÖZET .... IV"]


class TestManifestRow:
    RECORD = {
        "tez_id": "532507",
        "title": "Teza min",
        "url": "https://tez.yok.gov.tr/x",
        "pdf_file": "data/download/532507.pdf",
    }

    def test_counts_are_read_off_the_blocks(self, tmp_path):
        found = [
            Block("KURTE .... III", BlockType.INDEX, 3),
            Block("ÖZET .... IV", BlockType.INDEX, 3),
            Block("KURTE", BlockType.TITLE, 6),
            Block("yek", BlockType.TEXT, 6),
            Block("du", BlockType.LIST, 7),
        ]
        row = manifest_row(self.RECORD, found, blocks_path(self.RECORD, tmp_path))
        assert row == {
            "tez_id": "532507",
            "title": "Teza min",
            "url": "https://tez.yok.gov.tr/x",
            "blocks_file": str(tmp_path / "532507.blocks.json"),
            "block_count": 3,
            "heading_count": 1,
            "contents_entry_count": 2,
        }

    def test_the_pdf_path_is_not_forwarded(self, tmp_path):
        row = manifest_row(self.RECORD, [], blocks_path(self.RECORD, tmp_path))
        assert "pdf_file" not in row


class TestSelected:
    RECORDS = [{"tez_id": "1"}, {"tez_id": "2"}, {"tez_id": "3"}]

    @staticmethod
    def stage(only_theses: list[str]) -> ExtractStage:
        return ExtractStage(
            tier="basic", ocr_mode="auto", processing_window_size=16, only_theses=only_theses,
        )

    def test_an_empty_list_means_every_thesis(self):
        assert self.stage([]).selected(self.RECORDS) == self.RECORDS

    def test_only_the_named_theses_are_kept_in_manifest_order(self):
        assert self.stage(["3", "1"]).selected(self.RECORDS) == [{"tez_id": "1"}, {"tez_id": "3"}]

    def test_a_name_with_no_record_is_reported_not_raised(self, capsys):
        assert self.stage(["9"]).selected(self.RECORDS) == []
        assert "9" in capsys.readouterr().out


class TestParseOptions:
    """What MinerU is asked for. The call itself is never made here — it loads models."""

    def test_the_tier_and_ocr_mode_are_passed_through(self, extractor):
        options = extractor._parse_options()
        assert options["tier"] == "basic"
        assert options["ocr_mode"] == "auto"

    def test_image_analysis_is_off(self, extractor):
        """Every image, table and chart block is dropped, so describing them is work for
        output nothing reads."""
        assert extractor._parse_options()["image_analysis"] is False


class TestWindowSize:
    def test_the_processing_window_is_given_to_mineru(self, extractor, monkeypatch):
        """At MinerU's own default of 64 a multi-window document dies on 16GB."""
        monkeypatch.delenv("MINERU_PROCESSING_WINDOW_SIZE", raising=False)
        extractor._apply_window_size()
        assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "16"

    def test_an_existing_value_is_overridden(self, extractor, monkeypatch):
        """config.yml decides, not whatever the shell happens to export."""
        monkeypatch.setenv("MINERU_PROCESSING_WINDOW_SIZE", "64")
        extractor._apply_window_size()
        assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "16"


class TestNormalization:
    """Every string MinerU returns is NFC-normalized as it enters the pipeline.

    It used to be a stage of its own. These are its tests, moved here with the work.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "Jinûve Zîndîbûna Çanda Lîstikên Retro û Têkelbûna Teknolojîya Modern",
            "Van salên dawîyê vejîneka mezin çêdibe li ser çanda lîstikên retro.",
            "PÊŞGOTIN",
        ],
    )
    def test_decomposed_kurdish_comes_out_composed(self, extractor, text):
        """`ê`, `î` and `û` come out of PDFs decomposed often enough to matter."""
        decomposed = unicodedata.normalize("NFD", text)
        assert not unicodedata.is_normalized("NFC", decomposed)
        found = extractor._blocks(pages([block("text", decomposed)]))
        assert body_of(found)[0].text == text

    def test_headings_are_normalized_too(self, extractor):
        """Headings share `_text` with prose today; this is what keeps them sharing it."""
        found = extractor._blocks(
            pages([block("title", unicodedata.normalize("NFD", "PÊŞGOTIN"))])
        )
        assert body_of(found)[0].text == "PÊŞGOTIN"
        assert unicodedata.is_normalized("NFC", body_of(found)[0].text)

    def test_every_kind_of_string_is_normalized(self, extractor):
        """One pass over a page that has all three: a contents entry, a heading, prose."""
        nfd = lambda t: unicodedata.normalize("NFD", t)
        found = extractor._blocks(pages([
            block("index", nfd("KURTE.iv")),
            block("title", nfd("PÊŞGOTIN")),
            block("text", nfd("Ev nivîsa dirêj a kurmancî ye.")),
        ]))
        strings = toc_entries(found) + [b.text for b in body_of(found)]
        assert len(strings) == 3
        assert all(unicodedata.is_normalized("NFC", s) for s in strings)

    def test_the_contents_entries_are_normalized_too(self, extractor):
        """`sections.py` matches summary words against them; NFD would not match NFC."""
        found = extractor._blocks(
            pages([block("index", unicodedata.normalize("NFD", "KURTE.iv"))])
        )
        assert toc_entries(found) == ["KURTE.iv"]
        assert unicodedata.is_normalized("NFC", toc_entries(found)[0])

    def test_already_composed_text_is_unchanged(self, extractor):
        found = extractor._blocks(pages([block("text", "Kurdî û kurmancî")]))
        assert body_of(found)[0].text == "Kurdî û kurmancî"

    def test_ascii_is_unchanged(self, extractor):
        found = extractor._blocks(pages([block("text", "Hello world 123")]))
        assert body_of(found)[0].text == "Hello world 123"


class TestContentsRegion:
    """What of the front matter is the contents page, decided by position."""

    def test_the_contents_title_stays_a_heading(self, extractor):
        """MinerU 4 usually puts the title inside the `index` block (`443619`, `443622`,
        `388894`). Where it does not (`532507`), the word stays in the text. That costs one
        word out of 16.4 million, and it is why `get_content_title` was removed — the code
        is in `attic/contents_title.py`."""
        found = extractor._blocks(pages(
            [block("title", "NAVEROK"), block("index", "KURTE .... III")], FILLER
        ))
        assert toc_entries(found) == ["KURTE .... III"]
        assert "NAVEROK" in [b.text for b in body_of(found)]

    def test_a_heading_between_two_contents_blocks_is_a_contents_entry(self, extractor):
        """`447830`: `BEŞA YEKEM` came back as a heading between two contents blocks."""
        found = extractor._blocks(pages([
            block("index", "PÊŞGOTIN .... VI"),
            block("title", "BEŞA YEKEM"),
            block("index", "1.1. FEQIYÊ TEYRAN .... 5"),
        ], FILLER))
        assert toc_entries(found) == ["PÊŞGOTIN .... VI", "BEŞA YEKEM", "1.1. FEQIYÊ TEYRAN .... 5"]
        assert "BEŞA YEKEM" not in [b.text for b in body_of(found)]

    def test_the_same_heading_later_in_the_body_is_kept(self, extractor):
        """Position decides, not text: the real chapter heading has the same words."""
        found = extractor._blocks(pages(
            [block("index", "PÊŞGOTIN .... VI"), block("title", "BEŞA YEKEM"),
             block("index", "1.1. FEQIYÊ TEYRAN .... 5")],
            FILLER,
            [block("title", "BEŞA YEKEM"), block("text", "ev destpêka beşa yekem e")],
        ))
        headings = [b.text for b in body_of(found) if b.type is BlockType.TITLE]
        assert headings == ["BEŞA YEKEM"]

    def test_front_matter_between_two_contents_pages_stays(self, extractor):
        """`1003999`: 28 blocks — the summaries — sit between its contents and its list of
        figures. Only a single block between two contents blocks is taken."""
        found = extractor._blocks(pages([
            block("index", "KURTE .... VII"),
            block("title", "KURTE"),
            block("text", "Helbestvan Diya Ciwan jineke kurd e."),
            block("index", "Şekl 1. Çerxa Vergîlîus .... 21"),
        ], FILLER))
        assert [b.text for b in body_of(found)[:2]] == [
            "KURTE", "Helbestvan Diya Ciwan jineke kurd e."
        ]

    def test_an_index_block_deep_in_the_body_is_body_text(self, extractor):
        """`447830`: MinerU labelled 493 words of a poem on pages 128-148 as contents."""
        poem = "Were binve wek her car Xwedê mestire ji şah û xwindkar"
        found = extractor._blocks(pages(FILLER, [block("index", poem)]))
        assert toc_entries(found) == []
        assert body_of(found)[-1] == Block(text=poem, type=BlockType.TEXT, page=1)

    def test_a_heading_before_an_index_block_in_the_body_is_kept(self, extractor):
        """An `index` block in the body is body text, and the heading above it is a real
        heading."""
        found = extractor._blocks(pages(
            FILLER, [block("title", "Helbest"), block("index", "Were binve wek her car")]
        ))
        assert toc_entries(found) == []
        assert [b.text for b in body_of(found)[-2:]] == ["Helbest", "Were binve wek her car"]


class TestTypeMapping:
    """`BLOCK_TYPES`: which of MinerU's thirty-odd types this stage keeps."""

    def test_the_kept_types_are_mineru_s_own_strings(self):
        assert {str(t) for t in BLOCK_TYPES} == {
            "text", "ref_text", "doc_title", "paragraph_title", "list", "index"
        }

    def test_nothing_else_is_kept(self, extractor):
        for kind in ("page_number", "header", "footer", "aside_text", "page_footnote"):
            assert extractor._block_type(block(kind, "x").type) is None

    def test_an_index_block_outside_the_contents_region_is_written_as_text(self, extractor):
        assert extractor._block_type(block("index", "x").type) is BlockType.TEXT

    def test_a_title_type_maps_to_the_heading_type(self, extractor):
        assert extractor._block_type(block("title", "x").type) is BlockType.TITLE
        assert extractor._block_type(block("doc_title", "x").type) is BlockType.TITLE

    def test_a_contents_block_reads_back_as_its_entries(self, extractor):
        entries = block("index", "KURTE .... III", "ÖZET .... IV")
        assert extractor._contents_entries(entries) == ["KURTE .... III", "ÖZET .... IV"]

    def test_a_promoted_heading_is_one_entry(self, extractor):
        """A heading taken into the contents region has no nested entries of its own."""
        assert extractor._contents_entries(block("title", "BEŞA YEKEM")) == ["BEŞA YEKEM"]
