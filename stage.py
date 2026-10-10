from abc import ABC, abstractmethod
from pathlib import Path

import yaml

CONFIG_FILE = Path("config.yml")


class Stage(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def run(self, input_dir: Path | None, output_dir: Path) -> None: ...


def stage_config(name: str, config_path: Path = CONFIG_FILE) -> dict:
    """The tuning knobs `config.yml` gives one stage, ready to pass as keyword arguments.

    Every knob lives there and nowhere else — no stage defines a default in Python, so
    running a stage on its own and running it through `pipeline.py` cannot disagree.
    `description` is documentation, not a knob, so it is dropped.
    """
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {key: value for key, value in raw[name].items() if key != "description"}
