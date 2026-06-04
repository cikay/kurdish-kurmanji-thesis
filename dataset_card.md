---
language:
  - kmr
  - ku
license: cc-by-4.0
task_categories:
  - text-generation
  - fill-mask
pretty_name: Kurdish Kurmanji Academic Theses
tags:
  - kurdish
  - kurmanji
  - nlp
  - corpus
  - thesis
  - low-resource
---

# Kurdish Kurmanji Academic Theses

A corpus of Kurdish Kurmanji (Northern Kurdish, Latin script) text extracted from academic theses indexed in [YÖK Tez Merkezi](https://tez.yok.gov.tr), the Turkish national thesis repository.

## Dataset Summary

Each record is a single thesis whose body text has been filtered to Kurmanji-only paragraphs. Non-Kurdish paragraphs (Turkish, Arabic, etc.) and structural noise (figure captions, table of contents entries, bare page numbers) were removed using the [GlotLID v3](https://huggingface.co/cis-lmu/glotlid) language identifier.

## Fields

| Field | Type | Description |
|---|---|---|
| `tez_id` | string | Unique thesis ID from YÖK Tez Merkezi |
| `title` | string | Thesis title |
| `url` | string | URL to the original PDF |
| `word_count` | int | Word count of the cleaned Kurmanji text |
| `text` | string | Full cleaned Kurmanji text |

## Processing Pipeline

1. **Download** — PDFs fetched from YÖK Tez Merkezi
2. **Extract** — Plain text extracted from PDFs via PyMuPDF
3. **Normalize** — Text normalized to Unicode NFC
4. **Clean** — Paragraphs filtered to Kurmanji (`kmr_Latn`) using GlotLID v3 (min confidence 0.7)
5. **Stats** — Per-thesis word counts computed
6. **Filter** — Theses below minimum word count discarded

## Languages

Kurdish Kurmanji (`kmr`) in Latin script.

## Pipeline

The dataset was produced by the [kurdish-kurmanji-thesis](https://github.com/muzaffercky/kurdish-kurmanji-thesis) pipeline.
