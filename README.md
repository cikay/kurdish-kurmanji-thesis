# Kurdish Kurmanji Thesis Pipeline

Scrapes Kurdish-language theses from [YÖK Ulusal Tez Merkezi](https://tez.yok.gov.tr), extracts and normalizes their text, filters to Kurmanji-only content, and prepares it for publishing to Hugging Face.

## Pipeline stages

| Stage | Script | Input | Output |
|---|---|---|---|
| `download` | `download.py` | — | `data/download/*.pdf`, `manifest.jsonl` |
| `extract` | `extract.py` | `data/download/manifest.jsonl` | `data/extract/*.txt`, `manifest.jsonl` |
| `normalize` | `normalize.py` | `data/extract/manifest.jsonl` | `data/normalize/theses.csv` |
| `clean` | `clean.py` | `data/normalize/theses.csv` | `data/clean/theses.csv` |

Each stage writes its output to `data/{stage_name}/` and receives the previous stage's directory as input. No paths are hardcoded in stage classes.

## Usage

```bash
# Run all stages
python pipeline.py

# Start from a specific stage (skips earlier stages)
python pipeline.py --start-from extract

# Run a single stage only
python pipeline.py --only normalize

# Use a custom config file
python pipeline.py --config my_config.yml
```

## Installation

```bash
pipenv install
```

## Adding a stage

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

The pipeline automatically passes `data/{prev_stage_name}` as `input_dir` and `data/my_stage` as `output_dir`.
