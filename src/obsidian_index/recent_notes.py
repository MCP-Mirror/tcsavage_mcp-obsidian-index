from collections.abc import Sequence
from pathlib import Path

from obsidian_index.logger import logging

logger = logging.getLogger(__name__)


def find_recent_notes(vault_path: Path, top_n: int = 10) -> Sequence[Path]:
    """
    Finds the most recently modified notes in a vault.
    Paths are returned relative to the vault root.
    """
    logger.info("Looking for recent notes in %s", vault_path)
    paths = sorted(vault_path.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[
        :top_n
    ]
    paths = [path.relative_to(vault_path) for path in paths]
    logger.info("Finished looking for recent notes in %s", vault_path)
    return paths
