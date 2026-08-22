# Kurdish Kurmanji Thesis Pipeline

Scrapes Kurdish-language theses from [YÖK Ulusal Tez Merkezi](https://tez.yok.gov.tr), extracts and normalizes their text, filters to Kurmanji-only content, and publishes it to Hugging Face.

## Installation

```bash
pipenv install
```

## Usage

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

## Pipeline stages

| Stage | Script | Input | Output |
|---|---|---|---|
| `download` | `download.py` | — | `data/download/*.pdf`, `manifest.jsonl` |
| `extract` | `extract.py` | `data/download/manifest.jsonl` | `data/extract/*.txt`, `manifest.jsonl` |
| `normalize` | `normalize.py` | `data/extract/manifest.jsonl` | `data/normalize/theses.csv` |
| `clean` | `clean.py` | `data/normalize/theses.csv` | `data/clean/*.txt`, `manifest.jsonl` |
| `stats` | `stats.py` | `data/clean/manifest.jsonl` | `data/stats/manifest.jsonl` (adds `word_count`) |
| `filter` | `filter.py` | `data/stats/manifest.jsonl` | `data/filter/manifest.jsonl` (drops below `min_word_count`) |

Each stage writes its output to `data/{stage_name}/` and receives the previous stage's directory as input.

## Configuration

Stage parameters are defined in `config.yml`. The `filter` stage exposes `min_word_count`:

```yaml
filter:
  min_word_count: 100
```

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

The script uploads the dataset as Parquet (usable via `datasets.load_dataset()`) and pushes `dataset_card.md` as the repository README.

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
