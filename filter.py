"""Stage — Discard theses below a minimum word count."""

import json
from pathlib import Path

from stage import Stage


class FilterStage(Stage):
    name = "filter"

    def __init__(self, min_word_count: int = 1000):
        self._min_word_count = min_word_count

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(f"Filtering {len(records)} theses (min_word_count={self._min_word_count})")

        output_dir.mkdir(parents=True, exist_ok=True)
        kept = 0

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for record in records:
                if record["word_count"] >= self._min_word_count:
                    mf.write(json.dumps(record, ensure_ascii=False) + "\n")
                    kept += 1

        discarded = len(records) - kept
        print(f"Done — {kept} kept, {discarded} discarded → {output_dir}/manifest.jsonl")

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    stage = FilterStage()
    stage.run(Path("data/stats"), Path("data/filter"))
