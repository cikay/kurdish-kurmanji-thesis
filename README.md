# Kurdish Kurmanji Thesis Pipeline

Scrapes Kurdish-language theses from [YÖK Ulusal Tez Merkezi](https://tez.yok.gov.tr), extracts their text, and filters them for downstream use.

## Pipeline stages

| Stage | Script | Input | Output |
|---|---|---|---|
| `download` | `download.py` | — | `downloads/manifest.jsonl`, `downloads/<no>.pdf` |
| `split` | `split.py` | `downloads/manifest.jsonl` | `theses.csv` |
| `filter` | `filter.py` | `theses.csv` | `theses_filtered.csv` |

## Usage

```bash
# Run all stages
python pipeline.py

# Start from a specific stage (skips earlier stages)
python pipeline.py --start-from split

# Run a single stage only
python pipeline.py --only filter

# Use a custom config file
python pipeline.py --config my_config.yml
```

## Installation

```bash
pip install requests beautifulsoup4 lxml PyPDF2 pyyaml
```

## Adding a stage

1. Create a new script with a class that extends `Stage` from `stage.py`:

```python
from stage import Stage

class MyStage(Stage):
    name = "my_stage"

    def run(self) -> None:
        ...
```

2. Register it in `pipeline.py`:

```python
REGISTRY: dict[str, type[Stage]] = {
    ...
    "my_stage": MyStage,
}
```

3. Add it to `pipeline.yml`:

```yaml
stages:
  - ...
  - my_stage

my_stage:
  description: What this stage does
```
