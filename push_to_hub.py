"""Push the filtered dataset and dataset card to Hugging Face Hub."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from datasets import Dataset
from dotenv import load_dotenv
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError

load_dotenv()

logger = logging.getLogger(__name__)


def load_records(manifest_path: Path) -> list[dict]:
    with open(manifest_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_dataset(records: list[dict]) -> Dataset:
    rows = []
    for record in records:
        text = Path(record["txt_file"]).read_text(encoding="utf-8")
        rows.append(
            {
                "tez_id": record["tez_id"],
                "title": record["title"],
                "url": record["url"],
                "word_count": record["word_count"],
                "text": text,
            }
        )
    return Dataset.from_list(rows)


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

    ds = build_dataset(records)
    logger.info("Dataset ready — %d rows, columns: %s", len(ds), ds.column_names)

    logger.info("Pushing dataset to %s (private=%s)...", args.repo, args.private)
    ds.push_to_hub(args.repo, token=token, private=args.private)

    logger.info("Done — https://huggingface.co/datasets/%s", args.repo)


if __name__ == "__main__":
    main()
