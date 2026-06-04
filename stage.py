from abc import ABC, abstractmethod
from pathlib import Path


class Stage(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def run(self, input_dir: Path | None, output_dir: Path) -> None: ...
