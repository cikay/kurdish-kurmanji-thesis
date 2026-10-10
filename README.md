# Kurdish Kurmanji Thesis Pipeline

Scrapes Kurdish-language theses from [YÖK Ulusal Tez Merkezi](https://tez.yok.gov.tr), reads each PDF's layout with [MinerU](https://github.com/opendatalab/MinerU), takes each thesis's Kurmanji, Turkish and English summaries into their own columns, keeps the rest as text, and publishes the result to Hugging Face.

## Installation

```bash
pipenv install
```

### MinerU

The `extract` stage imports MinerU and calls it directly, so it is in the Pipfile
(`mineru==4.0.10`) and `pipenv install` brings it in, torch and transformers included — about
3 GB of wheels. On arm64 macOS the base package pulls `mineru[torch]` itself, so there is no
extra to choose. The first extraction then downloads about 1 GB of models to
`~/.cache/huggingface`.

MinerU used to live in a virtualenv of its own and run as a separate program, because
MinerU 3's `transformers` pinned `huggingface-hub` below 1.0 while this project wanted 1.17.0.
MinerU 4 needs `transformers>=5.10.1`, which has no such cap, so both live here now.

**The version is pinned for the output format, not only for reproducibility.** MinerU 4
returns the parsed document as objects — `pages` → `blocks` → `content`, in MinerU's own
`docvortex` schema — where 3.x wrote a `_middle.json` with `pdf_info` and `para_blocks`.
`extract.py` reads the 4.0 shape, so moving the pin back would mean rewriting it.

**Tiers.** `extract.tier` is how much work MinerU does per page: `basic` (used here) is the
layout-plus-OCR path, `flash` reads less, and `standard` and `advanced` add a local vision
model that takes two minutes to load before the first page.

**Memory.** MinerU reads a document in windows of pages. Its default window of 64 kills a
worker on 16 GB whenever a document needs more than one window, and the run ends with an
empty error message. `532507` (94 pages) fails at 64 and works at 16. The corpus averages 175
pages a thesis, so the default would fail on almost every thesis.
`extract.processing_window_size` sets it, and is 16.

**The window size also changes the text.** Two runs at 16 gave identical output. A run at 8
changed 120 of 1015 blocks — commas, full stops, Turkish `ı` against `i`. Keep it fixed.

## Usage

> **Before running `extract`**, check `extract.only_theses` in `config.yml`. It lists the
> `tez_id`s to extract. An empty list means all 420 PDFs, which is about 45 hours of MinerU.

```bash
# Run all stages
python pipeline.py

# Start from a specific stage (skips earlier stages)
python pipeline.py --start-from extract

# Run a single stage only
python pipeline.py --only filter

# Use a custom config file
python pipeline.py --config my_config.yml
```

The `sections` stage logs each thesis, each paragraph dropped for repeating a summary, and each
summary the contents page names but that was not found. `--debug` lowers the log level to
include successes as well.

### Running `extract` on Modal

`extract` is the slow stage, and each thesis is read on its own. `modal_extract.py` runs it
on [Modal](https://modal.com), one thesis per container and up to 40 containers at once, each
with a T4. The other stages stay on your machine.

```bash
modal volume create kurmanji-thesis                        # make the volume, once
modal volume put kurmanji-thesis data/download /download   # upload the PDFs, once
modal run --detach modal_extract.py                        # extract
modal volume get kurmanji-thesis /extract data/            # download the blocks files
python pipeline.py --start-from sections
```

**The volume.** A Modal volume is a disk that outlives the containers. This one holds the
same two folders as `data/` on your machine:

| On the volume | On your machine | What |
|---|---|---|
| `/download` | `data/download` | the PDFs and `manifest.jsonl`, which you upload |
| `/extract` | `data/extract` | the blocks files and `manifest.jsonl`, which the run writes |

The name `kurmanji-thesis` is `VOLUME_NAME` in `modal_extract.py`. The two have to match.

```bash
modal volume create kurmanji-thesis                 # make it
modal volume ls kurmanji-thesis /download           # see what is on it
modal volume rm -r kurmanji-thesis /extract         # delete the extracted files only
modal volume delete kurmanji-thesis                 # delete the volume and all on it
```

To start again from nothing, delete the volume, create it, and upload the PDFs again. To
upload over files that are already there, add `--force` to `modal volume put`.

Measured on a T4: `532507` (94 scanned pages) in 70s, where the Mac took 323s, and `1003999`
(164 pages, most with a text layer) in 74s. One container after another, the corpus would be
7 to 9 hours.

- The knobs come from `config.yml`, the same as a local run. A full pass still needs
  `extract.only_theses` to be empty.
- To try one thesis, name it in `extract.only_theses` before you start the run. The config
  is copied into the image when the run starts.
- `--no-gpu` uses CPU containers.
- A thesis whose blocks file is already on the volume is skipped, so a stopped run can be
  started again. To extract again with a changed knob, delete `/extract` on the volume first.
- One thesis may take two hours at most, then Modal ends it. A failed thesis is tried once
  more.
- `--detach` keeps the run going when the laptop is closed. Its output is in the Modal
  dashboard.
- **Do not mix Modal blocks files with ones made on the Mac.** A different device changes
  the OCR output in small ways, like a different window size does.

To look around by hand, open a shell in the same container the script uses — the code is in
`/root` and the volume is `/root/data`:

```bash
modal shell modal_extract.py::extract_on_gpu
```

## Pipeline stages

| Stage | Script | Input | Output |
|---|---|---|---|
| `download` | `download.py` | — | `data/download/*.pdf`, `manifest.jsonl` |
| `extract` | `extract.py` | `data/download/manifest.jsonl` | `data/extract/*.blocks.json`, `manifest.jsonl` (adds `block_count`, `heading_count`, `contents_entry_count`) |
| `sections` | `sections.py` | `data/extract/manifest.jsonl` | `data/sections/*.txt`, `manifest.jsonl` (adds `summaries`, `unrecovered_summaries`, `paragraph_count`) |
| `stats` | `stats.py` | `data/sections/manifest.jsonl` | `data/stats/manifest.jsonl` (adds `word_count`) |
| `filter` | `filter.py` | `data/stats/manifest.jsonl` | `data/filter/manifest.jsonl` (drops below `min_word_count` and where the whole text is in no wanted language; adds `text_lang`) |

Each stage writes its output to `data/{stage_name}/` and receives the previous stage's directory as input.

## Configuration

Stage parameters are defined in `config.yml`:

```yaml
extract:
  only_theses: ["532507"]      # the theses to extract; empty means all — ~45 hours
  tier: basic                  # layout + OCR; standard/advanced load a vision model
  ocr_mode: auto               # OCR a page when its text layer can't be read
  processing_window_size: 16   # 64 (MinerU's default) runs out of memory on 16 GB

sections:
  only_theses: []
  summary_min_words_before_heading: 50 # a heading that comes before a summary reaches this many words is title page
  min_words_for_lang_detect: 50  # a shorter section is too short to label, and is kept

filter:
  min_word_count: 1000
  text_langs:                  # GlotLID label of the whole text → the language (and subset) it is filed under
    kmr_Latn: kmr_Latn
    kiu_Latn: zza_Latn
    diq_Latn: zza_Latn
    ckb_Arab: ckb_Arab
    hac_Arab: hac_Arab         # six theses in old fonts; their text extracts damaged
```

## How a thesis is read

### `extract`: the PDF's structure

MinerU labels each piece of a page — a heading, a paragraph, an abstract, the contents page.
`extract.py` writes that as `<tez_id>.blocks.json`:

```json
[
  {"text": "NAVEROK…", "type": "index", "page": 3},
  {"text": "KURTE .............. III", "type": "index", "page": 3},
  {"text": "ÖZET..... IIV", "type": "index", "page": 3},
  {"text": "KURTE", "type": "title", "page": 6},
  {"text": "Ev xebat ji bo ...", "type": "abstract", "page": 6}
]
```

- The blocks are in reading order. Each keeps MinerU's type: `title`, `text`, `abstract`
  or `list`.
- **`index`** blocks are the contents page, one per line, kept exactly as printed.
- Page numbers, running heads, footnotes, images and tables are left out.
- All text is Unicode NFC.

MinerU's contents label is not always right, so `extract.py` corrects it by position:

- the heading just before the contents page is its title (`NAVEROK`, `İÇİNDEKİLER`,
  `CONTENTS`, or Zazaki `TEDEYÎ`), and becomes an `index` block;
- a single heading between two contents blocks is a contents entry, and becomes an `index`
  block;
- a block labelled "contents" after the first quarter of the thesis is really body text — a
  poem, a list — and is written as `text`.

### `sections`: summaries and text

`sections.py` cuts the blocks into sections at each heading, then:

- a section whose heading starts with `KURTE`, `ÖZET` or `ABSTRACT` becomes that language's
  summary. The first one in each language wins; a later one stays in the text.
- each summary is cut at its keywords line (`Peyvên Sereke:`, `Anahtar Kelimeler:`,
  `Keywords:`).
- a heading that arrives while a summary still has fewer than 50 words is the thesis title or
  author, and is dropped.
- a summary that is not in the language its heading claims becomes `null` (GlotLID). It is
  not moved to another column, and it does not go back into the text. 11 of 1151 summaries.
- a `ÇAVKANÎ` (bibliography) section is dropped.
- a section GlotLID labels none of Kurmanji, Zazaki and Sorani is dropped, unless it has
  fewer than 50 words. In the 407 Kurmanji theses that is about 242,000 of 18,763,980 words,
  mostly Turkish.
- everything else is `text`.

The summaries are one manifest field, `summaries`: a dict with the keys `kmr_Latn`,
`zza_Latn`, `ckb_Arab`, `tur_Latn` and `eng_Latn`, `null` where the thesis has none. Zazaki
summaries are under `KILMNUS`, `KILMVATE` or `KILMÎYE`, Sorani ones under `پوختە`.

### `filter`: which language a thesis is in

`filter.py` labels the whole text once and writes the result as `text_lang`. `push_to_hub.py`
pushes one subset per language:

| Subset | Theses | Words | Own-language summaries |
|---|---|---|---|
| `kmr_Latn` | 408 | 18,574,237 | 361 |
| `zza_Latn` | 29 | 1,162,986 | 21 |
| `ckb_Arab` | 4 | 105,254 | 4 |
| `hac_Arab` | 6 | 250,276 | 0 |

### Known limits

- **Which Kurdish language a thesis is in is judged per thesis, not per section.** Inside a
  Kurmanji thesis GlotLID labels 319,217 words of sections Zazaki, and the ones sampled were
  Kurmanji headings in capitals, glossaries and reference lists — so `sections` keeps all
  three languages, and `filter` names the thesis by its whole text.
- **Zazaki is one subset.** GlotLID has two labels for it and does not split the theses
  between them reliably.
- **Clean Sorani is only four theses.** Thirteen more Arabic-script theses are printed in
  old fonts and extract damaged; GlotLID labels them `hac_Arab`, `knc_Arab` or `arz_Arab`.
- **`hac_Arab` is a subset of damaged text, not of Gurani.** The six theses with that label
  are kept under it (`917623`, `517144`, `737293`, `473610`, `473612`, `484015`). They are
  Sorani and Kurmanji theses whose letters come out mapped wrong, like `ثەسچبٚ دەکەٚێذ`.
  Their Turkish and English abstracts are intact. The other seven damaged theses are
  dropped: six are under 1,000 words once their sections are judged, one is `arz_Arab`.
- **One thesis is in the wrong subset.** `458722` (51,759 words, in `kmr_Latn`) is Sorani
  in Latin letters.
- **`min_word_count` is 1000 for a reason.** At 100, `482021` and `447746` were kept in
  `zza_Latn` with 134 and 225 words: the short sections left of two damaged Arabic-script
  theses. The shortest real thesis has 7,076 words.
- About 43,000 words of Kurmanji abbreviation lists and tables are dropped, because GlotLID
  gives them labels like `frp_Latn`.
- A summary can start with title-page lines like `Master Thesis` or the author's name — 4 of
  54 sampled summaries, 53 words in all.
- An abstract shorter than 50 words would absorb the section after it.
- A short heading about sources, like `4.Çavkanî`, is dropped as if it were a bibliography.

## Extraction: what MinerU buys and what it costs

**It is slow.** Against about 4 pages a second for PyMuPDF, MinerU reads `532507` — 94
scanned pages, so every page is OCRed — at **0.29 pages a second** (323 s, tier `basic`).
MinerU 3.4.5 took 318 s for the same thesis, so **4.0 is no faster on a full thesis**; the
0.64 pages a second a 10-page probe showed was front matter, which is lighter than body
pages. A thesis with a readable text layer is quicker, so the corpus (73,604 pages across
420 PDFs) is somewhere between 45 and 70 hours on an M3. That is why `extract.only_theses`
exists.

**It wins where the PDF's text layer is unreadable**, which is the reason for the switch:

| | old (PyMuPDF + contents page) | MinerU |
|---|---|---|
| `532507` — 94 scanned pages | 63 words for the whole thesis | full text, all 3 summaries |
| `706158` — broken font cmap | `TEZA /Ì6$16$%ø/ø1'` | correct text, all 3 summaries |

42 of the 417 theses show that cmap corruption; 29 of them badly enough to matter, holding
1.28M words — 7.4% of the text the old pipeline kept.

**It loses where the contents page was readable.** MinerU merges a summary heading into the
title block above it, so `KURTE` disappears from the output entirely. Measured on the first 35
pages of 22 theses, grouped by what the old pipeline found:

| theses where the old split found | n | possible | old | MinerU |
|---|---|---|---|---|
| nothing | 10 | 30 | 3 | **30** |
| some summaries | 6 | 18 | **12** | 10 |
| all three | 6 | 18 | **18** | 14 |
| **total** | **22** | **66** | **33** | **54** |

`447830` and `887531` are the two clearest regressions.

The old contents-page reader, `toc.py` and its `TocParser`, is deleted. It is on the
branch `contents-driven-sections`; commit `2196edc` is the last one that used it.

### Summaries a thesis promised but never gave

The contents page is the one place a thesis *states* it has a `KURTE`. So a language the
contents page names, with no summary found for it, is reported in `unrecovered_summaries`. Without
that, a scanned abstract and an abstract the thesis never had would both just be `null`.

## Publishing to Hugging Face

Create a `.env` file with your token:

```
HF_TOKEN=hf_...
```

Then push:

```bash
# Public dataset
python push_to_hub.py --repo username/kurdish-kurmanji-theses

# Private dataset
python push_to_hub.py --repo username/kurdish-kurmanji-theses --private
```

The script uploads one subset per `text_lang` (`kmr_Latn`, `zza_Latn`, `ckb_Arab`, `hac_Arab`) as Parquet:

```python
from datasets import load_dataset
ds = load_dataset("username/kurdish-kurmanji-theses", "kmr_Latn", split="train")
```

It does **not** upload `dataset_card.md`. Upload that file as the repository's `README.md`
yourself after the push. Its `configs` block names the four subsets, so it is safe to
replace the README that the push generates. The numbers in the card are from one run;
update them if the data changes.

## Contributing

### Adding a stage

1. Create a class extending `Stage` from `stage.py`:

```python
from pathlib import Path
from stage import Stage

class MyStage(Stage):
    name = "my_stage"

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        ...
```

2. Register it in `pipeline.py`:

```python
REGISTRY: dict[str, type[Stage]] = {
    ...
    "my_stage": MyStage,
}
```

3. Add it to `config.yml`:

```yaml
stages:
  - ...
  - my_stage

my_stage:
  description: What this stage does
```

Any extra keys under the stage config are forwarded as kwargs to the stage constructor, so config-driven parameters work automatically.
