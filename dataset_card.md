---
language:
  - kmr
  - zza
  - ckb
  - ku
  - tr
  - en
license: cc-by-4.0
task_categories:
  - text-generation
  - fill-mask
  - summarization
  - translation
pretty_name: Kurdish Academic Theses (Kurmanji, Zazaki, Sorani)
tags:
  - kurdish
  - kurmanji
  - zazaki
  - sorani
  - nlp
  - corpus
  - thesis
  - low-resource
  - summarization
  - parallel-corpus
---

# Kurdish Academic Theses (Kurmanji, Zazaki, Sorani)

Text and abstracts of academic theses that [YÖK Tez Merkezi](https://tez.yok.gov.tr), the
Turkish national thesis repository, lists under Kurdish. Each row is one thesis.

## Subsets

A thesis is filed under the language of its text. There is one subset per language:

| Subset | Language | Theses | Words | Abstracts in that language |
|---|---|---|---|---|
| `kmr_Latn` | Kurmanji (Northern Kurdish), Latin script | 408 | 18,574,237 | 361 |
| `zza_Latn` | Zazaki, Latin script | 29 | 1,162,986 | 21 |
| `ckb_Arab` | Sorani (Central Kurdish), Arabic script | 4 | 105,254 | 4 |
| `hac_Arab` | Arabic-script theses whose text is damaged (see below) | 6 | 250,276 | 0 |

**`hac_Arab` is not usable as clean text.** The code is the one the language identifier
gave these six theses, and it stands for Gurani, but they are Sorani and Kurmanji theses
printed in old fonts. Their letters come out mapped wrong — `ثەسچبٚ دەکەٚێذ` where the
page reads differently. The subset is there so the theses are not lost, and so they stay
apart from the clean Sorani in `ckb_Arab`. Their Turkish and English abstracts are intact.

```python
from datasets import load_dataset

kurmanji = load_dataset("<repo>", "kmr_Latn", split="train")
zazaki = load_dataset("<repo>", "zza_Latn", split="train")
sorani = load_dataset("<repo>", "ckb_Arab", split="train")
damaged = load_dataset("<repo>", "hac_Arab", split="train")
```

## Fields

Every subset has the same fields.

| Field | Type | Description |
|---|---|---|
| `tez_id` | string | Thesis ID at YÖK Tez Merkezi |
| `title` | string | Thesis title |
| `url` | string | Link to the thesis at YÖK Tez Merkezi |
| `word_count` | int | Number of words in `text` |
| `text` | string | The body of the thesis: headings and paragraphs, separated by blank lines. The abstracts and the bibliography are not in it. |
| `summaries` | dict | The abstracts of the thesis, one key per language. A key is `null` when the thesis has no abstract in that language. |

The keys of `summaries` are the same in every row:

| Key | Abstract in | Heading it is printed under | Found |
|---|---|---|---|
| `kmr_Latn` | Kurmanji | `KURTE` | 363 |
| `zza_Latn` | Zazaki | `KILMNUS`, `KILMVATE`, `KILMÎYE` | 21 |
| `ckb_Arab` | Sorani | `پوختە` | 4 |
| `tur_Latn` | Turkish | `ÖZET` | 365 |
| `eng_Latn` | English | `ABSTRACT`, `SUMMARY` | 394 |

An abstract is typically 200 to 280 words.

## What it can be used for

- **Language modelling** on `text`.
- **Summarization**: `text` → an entry of `summaries`.
- **Translation**: one entry of `summaries` → another. Theses with both abstracts:
  Kurmanji–English 334, Turkish–English 333, Kurmanji–Turkish 319, Zazaki–English 21,
  Zazaki–Turkish 16.

The abstract a thesis prints in its front matter is taken out of `text`, so the summary is
not inside the text it summarizes. A thesis that prints its abstract a second time
elsewhere keeps that second copy in `text`.

## How it was made

1. **Download** — the PDFs are fetched from YÖK Tez Merkezi.
2. **Extract** — [MinerU](https://github.com/opendatalab/MinerU) 4.0 reads each PDF's
   layout and labels its blocks as headings, text or contents-page entries. Scanned pages
   are read with OCR. Tables, images, page numbers, headers and footers are dropped. Text
   is normalized to Unicode NFC.
3. **Sections** — the blocks are cut into sections at the headings.
   - A section under a summary heading becomes that language's abstract. It is cut at its
     keywords line. If [GlotLID v3](https://huggingface.co/cis-lmu/glotlid) says it is not
     in the language its heading names, it is discarded.
   - A section under a `ÇAVKANÎ` (bibliography) heading is discarded.
   - A section of 50 words or more that GlotLID labels neither Kurmanji, Zazaki nor Sorani
     is discarded. This removes Turkish and English pages and chapters.
   - Everything else is `text`.
4. **Filter** — GlotLID labels the whole `text` once, and that decides the subset. A thesis
   with fewer than 1,000 words, or with any other label, is dropped.

Of 457 downloaded theses, 447 are in the dataset.

## Known limits

- **The text comes from automatic layout analysis and OCR.** There are misread characters,
  and a heading can be attached to the wrong paragraph.
- **Some abstracts are missing or under the wrong heading.** On some pages MinerU puts the
  body of an abstract before its heading. The abstract is then lost, or filed under the
  previous heading and discarded by the language check. Where the contents page names an
  abstract that was not recovered, the entry is `null`.
- **An abstract can start with title-page lines**, such as `Master Thesis` or the author's
  name.
- **Language is judged per section, not per sentence.** A Turkish or English quotation
  inside a Kurmanji section stays in `text`, and so does any section under 50 words.
- **Zazaki is one subset.** GlotLID has two labels for it (`diq_Latn`, `kiu_Latn`) and does
  not separate these theses by them reliably.
- **Clean Sorani is only four theses.** Thirteen more theses in Arabic script use old fonts
  whose text cannot be extracted correctly. Six of them are in `hac_Arab`, damaged; the
  other seven are left out.
- **One thesis is in the wrong subset.** `458722` is in `kmr_Latn` but is Sorani written in
  Latin letters.
- **Reference lists under a heading other than `ÇAVKANÎ` are still in `text`.**

## Source and license

The theses are public documents published by YÖK Tez Merkezi; `url` links each row to its
source. The copyright of each thesis belongs to its author.

The dataset was produced by the
[kurdish-kurmanji-thesis](https://github.com/cikay/kurdish-kurmanji-thesis) pipeline.
