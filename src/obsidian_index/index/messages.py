from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IndexMessage:
    vault_name: str
    path: Path


@dataclass
class SearchRequestMessage:
    query: str


@dataclass
class SearchResponseMessage:
    paths: Sequence[Path]


@dataclass
class ExitMessage:
    pass
