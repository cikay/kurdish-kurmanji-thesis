"""Stage — Compute per-thesis word counts from clean text."""

import json
from pathlib import Path

from stage import Stage


class StatsStage(Stage):
    name = "stats"

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(f"Computing stats for {len(records)} theses")

        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for i, record in enumerate(records, 1):
                text = Path(record["txt_file"]).read_text(encoding="utf-8")
                word_count = len(text.split())
                mf.write(
                    json.dumps(
                        {**record, "thesis_word_count": word_count},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                print(f"  [{i}/{len(records)}]", end="\r")

        print(f"\nDone — stats written to {output_dir}/manifest.jsonl")

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    stage = StatsStage()
    stage.run(Path("data/sections"), Path("data/stats"))
