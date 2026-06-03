"""Run the thesis pipeline defined in pipeline.yml."""
import argparse
import sys
from pathlib import Path

import yaml

from download import TezScraper
from stage import Stage

REGISTRY: dict[str, type[Stage]] = {
    "download": TezScraper,

}


def load_config(config_path: Path) -> list[dict]:
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [{"name": name, **raw[name]} for name in raw["stages"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Kurdish-Kurmanji thesis pipeline.")
    parser.add_argument(
        "--start-from",
        metavar="STAGE",
        help="Name of the stage to start from (skips all earlier stages).",
    )
    parser.add_argument(
        "--only",
        metavar="STAGE",
        help="Run a single stage and exit.",
    )
    parser.add_argument(
        "--config",
        default="config.yml",
        metavar="FILE",
        help="Path to the pipeline YAML config (default: pipeline.yml).",
    )
    args = parser.parse_args()

    if args.start_from and args.only:
        print("Error: --start-from and --only are mutually exclusive.")
        sys.exit(1)

    stage_cfgs = load_config(Path(args.config))
    stage_names = [s["name"] for s in stage_cfgs]

    if args.only:
        if args.only not in stage_names:
            print(f"Error: unknown stage '{args.only}'. Valid stages: {', '.join(stage_names)}")
            sys.exit(1)
        stage_cfgs = [next(c for c in stage_cfgs if c["name"] == args.only)]
    elif args.start_from:
        if args.start_from not in stage_names:
            print(f"Error: unknown stage '{args.start_from}'. Valid stages: {', '.join(stage_names)}")
            sys.exit(1)
        stage_cfgs = stage_cfgs[stage_names.index(args.start_from):]

    for cfg in stage_cfgs:
        stage: Stage = REGISTRY[cfg["name"]]()
        print(f"\n=== Stage: {stage.name} — {cfg['description']} ===")
        stage.run()

    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
