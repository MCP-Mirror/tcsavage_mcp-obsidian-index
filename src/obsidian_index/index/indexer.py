import time
from collections.abc import Sequence
from pathlib import Path

from obsidian_index.index.database import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)


class Indexer:
    database: Database
    vaults: dict[str, Path]
    encoder: Encoder
    model_batch_size: int

    def __init__(
        self,
        database: Database,
        vaults: dict[str, Path],
        encoder: Encoder,
        model_batch_size: int = 16,
    ):
        self.database = database
        self.vaults = vaults
        self.encoder = encoder
        self.model_batch_size = model_batch_size

    def ingest_paths(self, vault_name_paths: Sequence[tuple[str, Path]]):
        logger.info("Ingesting %d paths", len(vault_name_paths))
        logger.info("Loading texts for %d paths", len(vault_name_paths))
        texts: list[str] = []
        for _, path in vault_name_paths:
            with open(path, "r") as f:
                texts.append(f.read())
        logger.info("Encoding texts for %d paths", len(vault_name_paths))
        time_emb_start = time.time()
        embs = self.encoder.encode_documents(texts, batch_size=self.model_batch_size)
        time_emb_stop = time.time()
        logger.info("Embedding %d docs took %.2fs", len(texts), time_emb_stop - time_emb_start)
        logger.info("Storing embeddings for %d paths", len(vault_name_paths))
        for (vault_name, path), emb in zip(vault_name_paths, embs, strict=True):
            # Store the note in the database
            # The path is stored relative to the vault root
            vault_rel_path = path.relative_to(self.vaults[vault_name])
            self.database.store_note(vault_rel_path, vault_name, path.stat().st_mtime, emb)  # type: ignore
