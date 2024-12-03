from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent

import duckdb
import torch

from obsidian_index.logging import logging

logger = logging.getLogger(__name__)


class Database:
    ddb_connection: duckdb.DuckDBPyConnection
    read_only: bool

    def __init__(self, database_path: Path, read_only: bool = False):
        self.ddb_connection = duckdb.connect(database_path, read_only=read_only)
        self.read_only = read_only

        if not self.read_only:
            self.initialize()

    def initialize(self):
        """
        Perform any necessary initialization of the database.
        """
        self.ddb_connection.execute(
            dedent("""
            CREATE TABLE IF NOT EXISTS notes (
                path STRING PRIMARY KEY,
                vault_name STRING,
                last_modified FLOAT,
                emb_minilm_l6_v2 FLOAT[384],
            )
        """)
        )

    def num_notes(self) -> int:
        """
        Get the total number of notes in the database.
        """
        return self.ddb_connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]  # type: ignore

    def get_most_recent_seen_timestamp(self, vault_name: str) -> float:
        """
        Get the most recent seen timestamp for a vault.
        """
        return self.ddb_connection.execute(
            "SELECT max(last_modified) FROM notes WHERE vault_name = ?", (vault_name,)
        ).fetchone()[0]  # type: ignore

    def store_note(
        self, path: Path, vault_name: str, last_modified: float, emb_minilm_l6_v2: list[float]
    ):
        """
        Store a note in the database.
        NOTE: The path should be relative to the vault root.
        """
        # DuckDB claims 'Not implemented Error: Array Update is not supported' when attempting to overwrite an array.
        # So we delete the row first if it exists.
        self.ddb_connection.execute(
            "DELETE FROM notes WHERE vault_name = ? AND path = ?", (vault_name, str(path))
        )
        self.ddb_connection.execute(
            "INSERT OR REPLACE INTO notes (path, vault_name, last_modified, emb_minilm_l6_v2) VALUES (?, ?, ?, ?)",
            (str(path), vault_name, last_modified, emb_minilm_l6_v2),
        )

    def search(self, query_emb: torch.Tensor, top_k: int = 1) -> Sequence[tuple[str, Path]]:
        """
        Search for notes similar to a query embedding.
        """
        results = self.ddb_connection.execute(
            "SELECT vault_name, path FROM notes ORDER BY emb_minilm_l6_v2 <-> ? LIMIT ?",
            (query_emb, top_k),
        )
        results = [(r[0], Path(r[1])) for r in results.fetchall()]
        return results
