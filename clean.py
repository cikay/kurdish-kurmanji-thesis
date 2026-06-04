"""Stage — Filter thesis text to Kurmanji-only paragraphs."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
import fasttext
from huggingface_hub import hf_hub_download

from stage import Stage


def load_lang_model():
    model_path = hf_hub_download(repo_id="cis-lmu/glotlid", filename="model_v3.bin")
    return fasttext.load_model(model_path)


lang_model = load_lang_model()


@dataclass
class CleanConfig:
    target_lang: str = "kmr_Latn"
    min_prob: float = 0.7


class Cleaner:
    """Filters thesis text down to target-language paragraphs and strips noise."""

    _BLANK_LINE_RE = re.compile(r"\n\s*\n")
    _BARE_NUMBER_RE = re.compile(r"^\d+$")
    _STRUCTURAL_RE = re.compile(
        r"^(şekil|tablo|figure|table|ek\s|appendix|içindekiler|contents)\b",
        re.IGNORECASE,
    )

    def __init__(self, config: CleanConfig):
        self._config = config

    def clean(self, text: str) -> tuple[str, dict]:
        paragraphs = self._split_paragraphs(text)
        kept = []
        stats = {
            "total_paragraphs": len(paragraphs),
            "kept_paragraphs": 0,
            "skipped_paragraphs": 0,
        }

        for p in paragraphs:
            if self._should_skip(p):
                stats["skipped_paragraphs"] += 1
                continue

            lang, prob = self._detect_lang(p)
            if lang == self._config.target_lang and prob >= self._config.min_prob:
                cleaned = self._strip_citation_lines(p)
                if cleaned:
                    kept.append(cleaned)
                    stats["kept_paragraphs"] += 1
                    continue

            stats["skipped_paragraphs"] += 1

        return "\n\n".join(kept), stats

    def _split_paragraphs(self, text: str) -> list[str]:
        text = text.replace(
            "\r\n", "\n"
        )  # PDF extraction often yields Windows line endings; normalize to Unix so the regex works consistently
        parts = self._BLANK_LINE_RE.split(text)
        return [p.strip("\n ") for p in parts if p.strip()]

    def _should_skip(self, p: str) -> bool:
        return self._is_structural(p)

    def _is_structural(self, p: str) -> bool:
        first_line = p.splitlines()[0] if p else ""
        return bool(self._STRUCTURAL_RE.match(first_line))

    def _detect_lang(self, text: str) -> tuple[str, float]:
        labels, probs = lang_model.predict(text.replace("\n", " "))
        return labels[0].replace("__label__", ""), float(probs[0])

    def _strip_citation_lines(self, p: str) -> str:
        lines = []
        for line in p.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if self._BARE_NUMBER_RE.match(stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()


class CleanStage(Stage):
    name = "clean"

    def __init__(self, config: CleanConfig | None = None):
        self._cleaner = Cleaner(config or CleanConfig())

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(f"Cleaning {len(records)} theses")

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for i, record in enumerate(records, 1):
                text = Path(record["txt_file"]).read_text(encoding="utf-8")
                cleaned, _ = self._cleaner.clean(text)
                if cleaned:
                    txt_file = output_dir / f"{record['tez_id']}.txt"
                    txt_file.write_text(cleaned, encoding="utf-8")
                    mf.write(
                        json.dumps(
                            {
                                "tez_id": record["tez_id"],
                                "title": record["title"],
                                "url": record["url"],
                                "txt_file": str(txt_file),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    saved += 1
                print(f"  [{i}/{len(records)}] cleaned: {saved}", end="\r")

        print(f"\nDone — {saved}/{len(records)} theses written to {output_dir}/")

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    stage = CleanStage()
    stage.run(Path("data/normalize"), Path("data/clean"))
