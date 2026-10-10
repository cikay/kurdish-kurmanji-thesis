"""Stage — Read each downloaded PDF's structure with MinerU, NFC-normalized.

This stage used to be PyMuPDF handing the next stage a wall of plain lines. Something had
to say which of those lines were headings, and the printed contents page was the only thing
in the document that did. MinerU labels them directly —
`paragraph_title` for a heading, `index` for the contents page, `page_number` and
`page_footnote` for the furniture — so the blocks arrive already sorted into headings and
prose.

Two things it buys that no text-layer extractor can. It renders and reads the page, so a
thesis whose front matter is scanned images is no longer blank: `532507` is 94 scanned
pages and PyMuPDF returned 63 words for the whole document. And it never touches the PDF's
own character map, so the theses whose embedded fonts are mis-mapped come out as words
instead of noise — `706158` extracted as `TEZA /Ì6$16$%ø/ø1'` and reads correctly here.

What it costs, measured on this corpus before the switch, is written down in the README so
the trade is not forgotten: on theses whose contents page *was* readable it finds fewer
summaries than the old split did, because it merges a summary heading into the title block
above it — the same failure Docling and Marker showed. It wins on the documents that were
unreadable and loses a little on the ones that already worked.

MinerU is **imported and called in-process**: `mineru.parse` returns the parsed document as
objects, so there is no subprocess, no output directory and no `_middle.json` to read back.
The blocks are `docvortex` models — MinerU's own document schema, a separate package — and
this module reads them directly instead of describing them again.

MinerU 4 is a different parser from the 3.x this stage was written against, and two of its
changes matter here. `pdf_info`/`para_blocks` are gone: a page is `page_idx` plus `blocks`,
a block's text is its `content` spans, and a contents page is one `index` block whose
`content` is a nested block per entry. And `discarded_blocks` is gone with them — the page
numbers and running heads MinerU used to keep out of the way now arrive in the same list,
which is what `BLOCK_TYPES` drops.

There is no timeout: a document that hangs hangs the stage. And when a window of pages does
not fit in memory MinerU kills a worker, which costs a worker inside this process — see
`processing_window_size` in `config.yml`.
"""
import json
import os
from pathlib import Path

from docvortex.schema import BlockType as MinerUType

from blocks import Block, BlockType, dump, line_text, normalize_nfc
from stage import Stage


# How far into a thesis, by reading-order position, an `index` block can still be its
# contents page. MinerU's `index` label is wrong in the body often enough to matter: over
# six full theses the real contents blocks sat at page 14 at the latest, and the false
# ones started at page 61 — poem lines (`447830`, 493 words), a list of stories
# (`465880`), a plagiarism report (`532507`). The first quarter is the bound the old
# contents-page parser already used for the same job, measured against all 417 theses.
CONTENTS_REGION = 0.25

# The span type that holds text. A block's `content` is split into spans where a formula
# (`equation_inline`), a hyperlink or a run of code sits inside the prose; only this one is
# words. A LaTeX formula is not text a language model should be pre-trained on as if it
# were.
TEXT_SPAN_TYPE = "text"

# What each MinerU type is written as, and by omission what is dropped. MinerU 4 names
# about thirty types; these are the ones that carry a thesis's words.
#
# - Both title types become one. MinerU calls a heading `doc_title` or `paragraph_title`
#   depending on how it reads the page, and it does not do so consistently: in `532507`
#   `ÖZET` is a `doc_title` and `KURTE` a `paragraph_title`, two pages apart. The levels
#   come from the same judgement and are not read either. What opens a section here is
#   being a heading at all.
# - `ref_text` is a bibliography entry. It stays text, as it was in 3.x, so that
#   `sections.py` keeps deciding what a bibliography is by its `ÇAVKANÎ` heading — one rule
#   for it, measured, instead of two that can disagree.
# - Everything absent is dropped: `page_number`, `header`, `footer`, `aside_text` and
#   `page_footnote` are the page furniture 3.x kept in `discarded_blocks`, and the image,
#   table, chart, code and equation families hold no Kurmanji prose.
BLOCK_TYPES = {
    MinerUType.TEXT: BlockType.TEXT,
    MinerUType.REF_TEXT: BlockType.TEXT,
    MinerUType.DOC_TITLE: BlockType.TITLE,
    MinerUType.PARAGRAPH_TITLE: BlockType.TITLE,
    MinerUType.LIST: BlockType.LIST,
    MinerUType.INDEX: BlockType.INDEX,
}


class MinerUExtractor:
    """Runs MinerU over one PDF and reads its labelled blocks back."""

    def __init__(self, tier: str, ocr_mode: str, processing_window_size: int):
        self._tier = tier
        self._ocr_mode = ocr_mode
        self._processing_window_size = processing_window_size

    def extract(self, pdf_path: Path) -> list[Block] | None:
        """The blocks of one PDF, or None if MinerU could not read it."""
        pages = self._parse(pdf_path)
        if pages is None:
            return None
        return self._blocks(pages)

    def _parse(self, pdf_path: Path) -> list | None:
        """MinerU's pages for one PDF, or None if it could not read the document.

        The import sits here and not at the top of the module because MinerU loads torch
        and its models: slow, and nothing but this method needs them, so importing
        `extract.py` — which the tests do — stays free.

        Any exception is a failed document, not a failed run: MinerU raises for a PDF it
        cannot open, and the stage has 416 more to read. A document that comes back with no
        pages at all is the same kind of failure, reported rather than written out.
        """
        import mineru

        self._apply_window_size()
        try:
            result = mineru.parse(str(pdf_path), **self._parse_options())
        except Exception as error:
            print(f"  MinerU failed ({pdf_path.name}): {type(error).__name__}: {error}")
            return None
        if not result.pages:
            print(f"  MinerU produced no pages ({pdf_path.name})")
            return None
        return result.pages

    def _blocks(self, pages: list) -> list[Block]:
        """The blocks MinerU kept, in reading order, with the contents page among them.

        The contents page comes out as `index` blocks, one per entry. Which blocks it is
        made of is decided by `_contents_positions`, so a heading can become one, and a
        block MinerU labelled `index` may not be one.
        """
        placed = [(block, page.page_idx) for page in pages for block in page.blocks]

        contents = self._contents_positions(placed)
        valid_blocks: list[Block] = []
        for position, (block, page_number) in enumerate(placed):
            if position in contents:
                # One written block per entry, kept whole. Run together they would weld
                # into `KURTE .... III ÖZET .... IIV` and lose where each one ends.
                valid_blocks.extend(
                    Block(text=entry, type=BlockType.INDEX, page=page_number)
                    for entry in self._contents_entries(block)
                )
                continue

            block_type = self._block_type(block.type)
            if block_type is None:
                continue

            text = self._text(block)
            if text:
                valid_blocks.append(Block(text=text, type=block_type, page=page_number))

        return valid_blocks

    def _parse_options(self) -> dict:
        """How MinerU is asked to read a document.

        `tier` picks how much work it does per page. `basic` is what this corpus runs on:
        it is the layout-plus-OCR path, the nearest thing to 3.x's `pipeline` backend, and
        it read 10 pages of `532507` in 15.6s against 3.4.5's 35s. `standard` and
        `advanced` add a local vision model — a two-minute load before the first page, and
        a per-page cost this corpus cannot afford at 73,604 pages.

        `image_analysis` is off because every image, table and chart block is dropped
        anyway: describing them is work for output nothing reads.
        """
        return {
            "tier": self._tier,
            "ocr_mode": self._ocr_mode,
            "image_analysis": False,
        }

    def _apply_window_size(self) -> None:
        """Tell MinerU how many pages it may hold at once.

        MinerU defaults to a 64-page window and **dies on this hardware** when a document
        needs more than one of them: `532507` is 94 scanned pages, and at the default it
        failed after the first window with an empty error message and a leaked-semaphore
        warning — a worker killed, which reads as the machine running out of memory. The
        same PDF's first 35 pages had gone through fine. The corpus averages 175 pages a
        thesis, so the default would fail almost everywhere.

        An environment variable because that is the only way MinerU takes it.
        `backend/analysis/pdf/window.py` reads `MINERU_PROCESSING_WINDOW_SIZE` when the
        analysis starts, not when the module is imported, so setting it here is in time.
        """
        os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = str(self._processing_window_size)

    @classmethod
    def _contents_positions(cls, placed: list[tuple]) -> set[int]:
        """Which blocks, by reading-order position, make up the thesis's contents pages.

        MinerU's `index` label is where this starts, but it is wrong in both directions,
        and both corrections below were measured over six fully extracted theses.

        The contents page's own title is not handled here any more. MinerU 4 usually puts
        it inside the `index` block (`443619`, `443622`, `388894`); where it does not
        (`532507`), the word stays a heading in `text`.

        - An `index` block past the first quarter of the thesis is not the contents. It is
          body text MinerU mislabelled, and it goes back into the blocks rather than
          vanishing into the contents page. See `CONTENTS_REGION`.
        - A single block between two contents blocks is a contents entry MinerU
          mislabelled, whatever it labelled it as — the gap is what says so, not the type.
          Every one-block gap in the sample happened to be a heading: `BEŞA YEKEM` to
          `BEŞA ÇAREM` (`447830`), `LÎSTEYA ŞEKLAN` and `LÎSTEYA WÊNEYAN` (`1003999`),
          `LÎSTEYA TABLO Û ŞIKLAN` (`887531`). Only a single block: a wider gap is real
          front matter — in `1003999` the 28 blocks between its contents and its list of
          figures are the summaries.

        Position matters, not text: `BEŞA YEKEM` is also the real first chapter heading
        further on, so matching the contents page's words against the body would delete it.
        """
        limit = len(placed) * CONTENTS_REGION
        contents_at = [
            position
            for position, (block, _) in enumerate(placed)
            if block.type == MinerUType.INDEX and position < limit
        ]

        region = set(contents_at)
        for before, after in zip(contents_at, contents_at[1:]):
            if after - before == 2:
                region.add(before + 1)

        return region

    @classmethod
    def _contents_entries(cls, block) -> list[str]:
        """One or more contents entries per block.

        MinerU gives the whole contents page as one `index` block. Inside that block
        there is one small block for each line on the page: `KURTE.. ...Ⅱ`, `ÖZET... .`,
        `1.2.1.Pêşdaçek.. 9`. So we read the lines from those small blocks. We do not have
        to cut one long string into lines.

        Some blocks here are not a contents page. `_contents_positions` also picks single
        blocks: the title of the page (`NAVEROK`), and a block that sits alone between two
        contents blocks (`BEŞA YEKEM`). These have no small blocks inside, only text. So
        the text of the block itself is the one entry.
        """
        content = getattr(block, "content", None) or []
        # A nested block carries MinerU's own type; a span's type is a plain string. That
        # is the only difference between them here, since both have `content`.
        nested_blocks = [item for item in content if isinstance(getattr(item, "type", None), MinerUType)]
        entries = [text for text in (cls._text(item) for item in nested_blocks) if text]
        if entries:
            return entries
        text = cls._text(block)
        return [text] if text else []

    @classmethod
    def _text(cls, block) -> str:
        """The text of one block.

        Every string this stage makes comes from here: contents entries, headings and
        prose. So we fix the letters here, in one place, and the whole pipeline is safe.

        The fix is `normalize_nfc`. Kurdish `ê`, `î` and `û` often come out of a PDF in
        two pieces: the letter, then the accent. On screen you see `Î`, the same as a
        one-piece `Î`. But for Python they are two different strings. Then `==` is False,
        a regex does not match, and `in` does not find it.

        Spans are joined with nothing between them. A span is a piece of a line, not a
        line. MinerU cuts a new span where the style changes, and that cut can fall inside
        a word: `Kur` + `mancî`. The spaces the page had are already inside each span.
        """
        content = getattr(block, "content", None)
        if not content or isinstance(content, str):
            # An equation block's `content` is its LaTeX, a bare string. Dropped anyway.
            return ""
        spans = "".join(
            item.content
            for item in content
            if getattr(item, "type", None) == TEXT_SPAN_TYPE
            and isinstance(getattr(item, "content", None), str)
        )
        # A list's items and a contents page's entries are nested blocks, not spans. Each
        # is a line of its own, so these are joined with a space and the spans without one.
        nested = " ".join(
            text
            for text in (
                cls._text(item)
                for item in content
                if isinstance(getattr(item, "type", None), MinerUType)
            )
            if text
        )
        return line_text(normalize_nfc(" ".join(part for part in (spans, nested) if part)))

    @classmethod
    def _block_type(cls, block_type) -> BlockType | None:
        """The type a kept block is written with, or None for a type this stage drops.

        MinerU's own type is kept, as mapped by `BLOCK_TYPES`, with one correction: an
        `index` block only reaches here when it is outside the contents region — body text
        MinerU mislabelled — so it is written as `text`.
        """
        if block_type == MinerUType.INDEX:
            return BlockType.TEXT
        return BLOCK_TYPES.get(block_type)


def blocks_path(record: dict, output_dir: Path) -> Path:
    """Where one thesis's blocks file is written."""
    return output_dir / f"{record['tez_id']}.blocks.json"


def manifest_row(record: dict, blocks: list[Block], blocks_file: Path) -> dict:
    """The manifest row for one extracted thesis.

    Only these fields go on: the input is the download manifest, and `pdf_file` has no
    business downstream. Every count is read off the blocks, so a row can be made again
    from a blocks file already on disk, without running MinerU a second time.
    """
    return {
        "tez_id": record["tez_id"],
        "title": record["title"],
        "url": record["url"],
        "blocks_file": str(blocks_file),
        "block_count": sum(1 for b in blocks if b.type is not BlockType.INDEX),
        "heading_count": sum(1 for b in blocks if b.is_heading),
        "contents_entry_count": sum(1 for b in blocks if b.type is BlockType.INDEX),
    }


class ExtractStage(Stage):
    name = "extract"

    def __init__(
        self,
        tier: str,
        ocr_mode: str,
        processing_window_size: int,
        only_theses: list[str] | None = None,
    ):
        # `only_theses` selects what to run, it does not tune it, so it is not passed to
        # the extractor — same split as the sections stage makes.
        self._only_theses = set(only_theses) if only_theses is not None else set()
        self._extractor = MinerUExtractor(
            tier=tier,
            ocr_mode=ocr_mode,
            processing_window_size=processing_window_size,
        )

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self.selected(self._load_manifest(input_dir / "manifest.jsonl"))

        print(f"Extracting {len(records)} PDFs with MinerU")

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as manifest_file:
            for number, record in enumerate(records, 1):
                print(f"  [{number}/{len(records)}] {record['tez_id']}", flush=True)

                row = self.extract_one(record, output_dir)
                if row is None:
                    continue

                manifest_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                manifest_file.flush()

                saved += 1

        print(f"\nDone — {saved}/{len(records)} theses extracted to {output_dir}/")

    def selected(self, records: list[dict]) -> list[dict]:
        """The records `only_theses` names, or every record when it names none."""
        if not self._only_theses:
            return records
        records = [r for r in records if r["tez_id"] in self._only_theses]
        missing = self._only_theses - {r["tez_id"] for r in records}
        if missing:
            print(f"  only_theses: no manifest record for {', '.join(sorted(missing))}")
        return records

    def extract_one(self, record: dict, output_dir: Path) -> dict | None:
        """Extract one thesis: write its blocks file, return its manifest row.

        None when MinerU could not read the PDF, or read nothing but a contents page.
        One thesis at a time, and no manifest file touched, so that something other than
        `run` can drive it — `modal_extract.py` gives each thesis its own container.
        """
        blocks = self._extractor.extract(Path(record["pdf_file"]))
        if blocks is None or all(b.type is BlockType.INDEX for b in blocks):
            return None

        blocks_file = blocks_path(record, output_dir)
        dump(blocks, blocks_file)
        return manifest_row(record, blocks, blocks_file)

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    from stage import stage_config

    ExtractStage(**stage_config("extract")).run(Path("data/download"), Path("data/extract"))
