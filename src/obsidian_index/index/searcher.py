from collections.abc import Sequence
from pathlib import Path

from obsidian_index.index.database import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.logging import logging

logger = logging.getLogger(__name__)


class Searcher:
    database: Database
    vaults: dict[str, Path]
    encoder: Encoder

    def __init__(
        self,
        database_path: Path,
        vaults: dict[str, Path],
        encoder: Encoder,
    ):
        self.database = Database(database_path, read_only=True)
        self.vaults = vaults
        self.encoder = encoder

    def search(self, query: str, top_k: int = 10) -> Sequence[Path]:
        """
        Search for notes that match a query.
        """
        query_emb = self.encoder.encode_query(query)

        results = self.database.search(query_emb, top_k=top_k)  # type: ignore
        # Join that vault path with the note path to get the full path.
        resolved_paths = [self.vaults[result[0]] / result[1] for result in results]
        return resolved_paths
