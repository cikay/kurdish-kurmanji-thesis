"""Push the filtered dataset and dataset card to Hugging Face Hub."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from datasets import Dataset, Features, Value
from dotenv import load_dotenv
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError

from sections import SUMMARY_LANGUAGES

load_dotenv(override=True)

logger = logging.getLogger(__name__)


def load_records(manifest_path: Path) -> list[dict]:
    with open(manifest_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# Stated rather than inferred: a subset where no thesis has a summary in some language
# would otherwise type that key `null`, and the subsets would not share a schema.
FEATURES = Features(
    {
        "tez_id": Value("string"),
        "title": Value("string"),
        "url": Value("string"),
        "word_count": Value("int64"),
        "text": Value("string"),
        "summaries": {lang: Value("string") for lang in SUMMARY_LANGUAGES},
    }
)


def build_datasets(records: list[dict]) -> dict[str, Dataset]:
    """One dataset per language a thesis is written in — the subsets of the repo.

    `text_lang` is written by the filter stage: `kmr_Latn`, `zza_Latn` or `ckb_Arab`.
    `summaries` has the same keys in every row, `null` where a thesis has no summary in
    that language, because a dict column needs one shape.
    """
    rows: dict[str, list[dict]] = {}
    for record in records:
        text = Path(record["txt_file"]).read_text(encoding="utf-8")
        rows.setdefault(record["text_lang"], []).append(
            {
                "tez_id": record["tez_id"],
                "title": record["title"],
                "url": record["url"],
                "word_count": record["thesis_word_count"],
                "text": text,
                "summaries": record["summaries"],
            }
        )
    return {
        lang: Dataset.from_list(lang_rows, features=FEATURES)
        for lang, lang_rows in sorted(rows.items())
    }


def check_repo_does_not_exist(repo_id: str, token: str) -> None:
    api = HfApi()
    try:
        api.dataset_info(repo_id=repo_id, token=token)
        raise RuntimeError(
            f"Dataset '{repo_id}' already exists on HuggingFace. "
            "Delete it first or choose a different name."
        )
    except RepositoryNotFoundError:
        pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Push dataset to Hugging Face Hub.")
    parser.add_argument("--repo", required=True, help="Hub repo ID, e.g. username/dataset-name")
    parser.add_argument(
        "--manifest",
        default="data/filter/manifest.jsonl",
        metavar="FILE",
        help="Path to the filter stage manifest (default: data/filter/manifest.jsonl)",
    )
    parser.add_argument("--private", action="store_true", help="Create as private dataset")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        logger.error("HF_TOKEN env variable not set")
        sys.exit(1)

    logger.info("Checking if '%s' already exists...", args.repo)
    check_repo_does_not_exist(args.repo, token)

    records = load_records(Path(args.manifest))
    logger.info("Loaded %d records from %s", len(records), args.manifest)

    datasets = build_datasets(records)
    for lang, ds in datasets.items():
        logger.info("Subset %s ready — %d rows, columns: %s", lang, len(ds), ds.column_names)

    for lang, ds in datasets.items():
        logger.info("Pushing subset %s to %s (private=%s)...", lang, args.repo, args.private)
        ds.push_to_hub(args.repo, config_name=lang, token=token, private=args.private)

    logger.info("Done — https://huggingface.co/datasets/%s", args.repo)


if __name__ == "__main__":
    main()
