"""Stage — Discard theses that are too short or not in a wanted language."""

import json
from collections import Counter
from pathlib import Path

from langid import detect_lang
from stage import Stage, stage_config


class FilterStage(Stage):
    name = "filter"

    def __init__(self, min_word_count: int, text_langs: dict[str, str]):
        self._min_word_count = min_word_count
        self._text_langs = text_langs

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(
            f"Filtering {len(records)} theses (min_word_count={self._min_word_count}, "
            f"text_langs={sorted(set(self._text_langs.values()))})"
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        kept, discarded = Counter(), Counter()

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for record in records:
                text_lang, reason = self.judge(record)
                if reason:
                    discarded[reason] += 1
                    continue
                mf.write(json.dumps({**record, "text_lang": text_lang}, ensure_ascii=False) + "\n")
                kept[text_lang] += 1

        print(f"Done — {sum(kept.values())} kept ({self._counts(kept)}),")
        print(f"       {sum(discarded.values())} discarded ({self._counts(discarded)})")
        print(f"       → {output_dir}/manifest.jsonl")

    def judge(self, record: dict) -> tuple[str | None, str | None]:
        """The language a kept thesis is in, or the reason a dropped one is dropped.

        The language is one GlotLID label over the whole text, looked up in `text_langs`.
        `sections` cannot do this part: it judges a section at a time, and there a Zazaki
        label is mostly a Kurmanji heading or glossary, so it lets all three languages
        through. Over a whole thesis the label is reliable — see `text_langs` in
        `config.yml`.
        """
        if record["thesis_word_count"] < self._min_word_count:
            return None, "too short"
        label = detect_lang(Path(record["txt_file"]).read_text(encoding="utf-8"))[0]
        if label not in self._text_langs:
            return None, f"text is {label}"
        return self._text_langs[label], None

    @staticmethod
    def _counts(counter: Counter) -> str:
        return ", ".join(f"{count} {name}" for name, count in counter.most_common())

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    stage = FilterStage(**stage_config("filter"))
    stage.run(Path("data/stats"), Path("data/filter"))
