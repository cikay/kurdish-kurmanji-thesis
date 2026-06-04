"""Stage — Normalize Kurdish Kurmanji text to NFC."""
import json
import unicodedata
from pathlib import Path
from typing import Callable

from stage import Stage


Transform = Callable[[str], str]


class Normalizer:
    """Applies a chain of text transforms."""

    def __init__(self):
        self._transforms = self._default_transforms()

    def normalize(self, text: str) -> str:
        for transform in self._transforms:
            text = transform(text)
        return text

    @staticmethod
    def _default_transforms() -> list[Transform]:
        return [
            lambda t: unicodedata.normalize("NFC", t),
        ]


class NormalizeStage(Stage):
    name = "normalize"

    def __init__(self):
        self._normalizer = Normalizer()

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(f"Normalizing {len(records)} theses")

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for i, record in enumerate(records, 1):
                text = Path(record["txt_file"]).read_text(encoding="utf-8")
                normalized = self._normalizer.normalize(text)
                txt_file = output_dir / f"{record['tez_id']}.txt"
                txt_file.write_text(normalized, encoding="utf-8")
                mf.write(json.dumps({
                    "tez_id": record["tez_id"],
                    "title": record["title"],
                    "url": record["url"],
                    "txt_file": str(txt_file),
                }, ensure_ascii=False) + "\n")
                saved += 1
                print(f"  [{i}/{len(records)}] normalized: {saved}", end="\r")

        print(f"\nDone — {saved}/{len(records)} txt files saved to {output_dir}/")

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    stage = NormalizeStage()
    stage.run(Path("data/extract"), Path("data/normalize"))
