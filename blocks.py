"""What one PDF came out of MinerU as — a list of `Block`s — and the file `extract` writes.

Every block carries MinerU's type, so a thesis is one flat list in reading order: its
headings, its prose, and its printed contents page as `index` blocks. The labels are the
whole point of the extract stage — a plain-text extractor hands the next stage a wall of
lines and leaves it to guess which are headings, and guessing is what `toc.py` was written
to avoid.

The contents page is **one `index` block per entry**, because that is what it is: one line
per heading the thesis promises. MinerU gives every block its lines, and joining a contents
page's lines into one string welds the entries together —
`'KURTE .... III ÖZET .... IIV ABSTRACT .... V'` — which cannot be read back apart. Kept
as lines, 19 of 22 sampled theses yield a clean ordered list of what the thesis says it
contains; welded into one string, 14 of 24 did.

Kept deliberately small. MinerU's own `_middle.json` carries bounding boxes, span fonts,
table HTML, block scores and a dozen types; none of that survives into `sections.py`, so
none of it is written out.
"""
import json
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class BlockType(StrEnum):
    """The MinerU block types this project reads, and the type of every `Block` it writes.

    MinerU defines about forty (`mineru/utils/enum_class.py`: image, table, chart, caption,
    footnote, code, header, footer, page_number, ...). Only these five are named, because
    only these five change what the pipeline does. Any other type stays the plain string
    MinerU wrote — see `parse` — and `extract.py` drops the block.

    A `StrEnum`, so `BlockType.TITLE == "title"`: a type still equals the string in
    `_middle.json` and in `blocks.json`.
    """

    # A heading. MinerU gives each one a `level`, which is not read: what opens a section is
    # being a heading at all, and the levels come from the same layout model that merges a
    # summary heading into the title above it.
    TITLE = "title"
    # Prose.
    TEXT = "text"
    # Prose, as its own type. MinerU 3 returned a summary page's body as this; MinerU 4
    # has no abstract type and returns it as `text`, so nothing writes this any more. Kept
    # so that a file written before the upgrade still loads.
    ABSTRACT = "abstract"
    # Prose, as list items.
    LIST = "list"
    # A line of the printed contents page, as `extract.py` decided it — which can be a
    # heading MinerU mislabelled. An `index` block MinerU put in the body is written as `text`.
    INDEX = "index"

    @classmethod
    def parse(cls, value: str) -> "BlockType | str":
        """The member for a type the pipeline reads, or the string itself for any other."""
        try:
            return cls(value)
        except ValueError:
            return value


@dataclass(frozen=True)
class Block:
    """One labelled block of a page, in reading order."""

    text: str
    # MinerU's own type for the block. `extract.py` only writes `BlockType` members.
    type: BlockType
    page: int

    @property
    def is_heading(self) -> bool:
        return self.type is BlockType.TITLE

    def to_dict(self) -> dict:
        return {"text": self.text, "type": str(self.type), "page": self.page}

    @classmethod
    def from_dict(cls, raw: dict) -> "Block":
        return cls(text=raw["text"], type=BlockType(raw["type"]), page=raw["page"])


def dump(blocks: list[Block], path: Path) -> None:
    path.write_text(
        json.dumps([block.to_dict() for block in blocks], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def load(path: Path) -> list[Block]:
    return [Block.from_dict(raw) for raw in json.loads(path.read_text(encoding="utf-8"))]


def toc_entries(blocks: list[Block]) -> list[str]:
    """The contents page's entries, in order: the text of the `index` blocks.

    The contents page is the one place a thesis *states* which summaries it has, so a
    language named here with no summary to show for it is a page that failed to extract,
    not a summary the thesis never had. Entries are kept verbatim, leaders and page numbers
    included — where an entry breaks says nothing, and trimming would only lose information.
    """
    return [block.text for block in blocks if block.type is BlockType.INDEX]


def normalize_nfc(text: str) -> str:
    """Text in composed form.

    Kurdish `ê`, `î` and `û` come out of PDFs decomposed often enough to matter, and a
    decomposed `Î` is a different string from a composed one — it fails an equality test,
    a regex and a `in` check alike, while looking identical on screen. Every string this
    pipeline holds is composed, and it is composed here, at the one point where MinerU's
    text enters. This used to be a stage of its own: a second pass over every file to
    change one property of every string.
    """
    return unicodedata.normalize("NFC", text)


def line_text(line: str) -> str:
    """A line with its runs of whitespace squeezed to one space.

    PDFs space words out where the typesetting did (`"Bu  tezin  kabulü"`), so the squeeze
    is needed. Nothing else is repaired: the hyphen-healing this once did fired 77 times
    against the corpus and every one was a false positive (`Kurdistan- A Selection` →
    `KurdistanA Selection`).

    Applied per line and never to a whole block, because `str.split()` splits on newlines
    too — squeezing a block would undo any line structure kept inside it.
    """
    return " ".join(line.split())
