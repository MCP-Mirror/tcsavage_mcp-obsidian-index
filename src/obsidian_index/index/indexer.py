import threading
import time
from collections import deque
from collections.abc import Iterable, Sequence
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from obsidian_index.index.database import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.logging import logging

logger = logging.getLogger(__name__)


class Indexer:
    database: Database
    vaults: dict[str, Path]
    encoder: Encoder
    ingest_queue: deque[tuple[str, Path]]
    wait_cv: threading.Condition
    directory_watchers: list["DirectoryWatcher"]
    ingest_batch_size: int
    model_batch_size: int

    def __init__(
        self,
        database_path: Path,
        vaults: dict[str, Path],
        encoder: Encoder,
        watch: bool = False,
        ingest_batch_size: int = 32,
        model_batch_size: int = 16,
    ):
        self.database = Database(database_path)
        self.vaults = vaults
        self.encoder = encoder
        self.ingest_queue = deque()
        self.ingest_batch_size = ingest_batch_size
        self.model_batch_size = model_batch_size
        self.wait_cv = threading.Condition()

        if self.database.num_notes() == 0:
            self.enqueue_all_note_paths_for_ingestion()
            # TODO: Enqueue any notes that were created/updated since the most recent timestamp in the database.

        if watch:
            self.directory_watchers = [
                DirectoryWatcher(self, vault_name, root, recursive=True)
                for vault_name, root in vaults.items()
            ]
            for watcher in self.directory_watchers:
                watcher.start()

    def run_ingestor(self, stop_when_done: bool = False):
        logger.info("Starting ingest loop")
        while self.ingest_queue or not stop_when_done:
            with self.wait_cv:
                self.wait_cv.wait_for(lambda: bool(self.ingest_queue))
                self._do_ingest_batch()
        logger.info("Stopping ingest loop")

    def _do_ingest_batch(self):
        batch: list[tuple[str, Path]] = []
        while self.ingest_queue and len(batch) < self.ingest_batch_size:
            vault_name_path = self.ingest_queue.popleft()
            batch.append(vault_name_path)

        logger.info(
            "Collected batch of %d paths (%d still in queue)", len(batch), len(self.ingest_queue)
        )

        self._do_ingest_paths(batch)

    def _do_ingest_paths(self, vault_name_paths: Sequence[tuple[str, Path]]):
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

    def enqueue_path_for_ingestion(self, vault_name: str, path: Path):
        if path.is_file():
            self.ingest_queue.append((vault_name, path))
            with self.wait_cv:
                self.wait_cv.notify_all()
        else:
            logger.warning("Path is not a file: %s", path)

    def find_all_note_paths(self) -> Iterable[tuple[str, Path]]:
        logger.info("Finding all note paths...")
        for vault_name, root in self.vaults.items():
            logger.info("Searching in root: %s...", root)
            for path in root.rglob("*.md"):
                logger.info("Found note: %s", path)
                yield vault_name, path

    def enqueue_all_note_paths_for_ingestion(self):
        for vault_name, path in self.find_all_note_paths():
            self.enqueue_path_for_ingestion(vault_name, path)


class DirectoryWatcher:
    """
    A class to watch directory changes and trigger callbacks on file events.
    """

    vault_name: str
    directory: Path
    indexer: Indexer
    recursive: bool

    def __init__(self, indexer: Indexer, vault_name: str, directory: Path, recursive: bool = False):
        self.indexer = indexer
        self.vault_name = vault_name
        self.directory = Path(directory)
        self.recursive = recursive
        self.observer = Observer()

    def start(self) -> None:
        event_handler = _FSEventHandler(self.indexer, self.vault_name, self.directory)
        self.observer.schedule(
            event_handler,
            str(self.directory),
            recursive=self.recursive,
            event_filter=[
                FileCreatedEvent,
                FileModifiedEvent,
                FileDeletedEvent,
                FileMovedEvent,
            ],
        )
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join()


class _FSEventHandler(FileSystemEventHandler):
    """
    Internal event handler class to process filesystem events.
    """

    vault_name: str
    directory: Path
    indexer: Indexer

    def __init__(self, indexer: Indexer, vault_name: str, directory: Path):
        self.indexer = indexer
        self.vault_name = vault_name
        self.directory = directory
        super().__init__()

    def on_created(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                self.indexer.enqueue_path_for_ingestion(self.vault_name, path.resolve())

    def on_modified(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                self.indexer.enqueue_path_for_ingestion(self.vault_name, path.resolve())

    def on_deleted(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                logger.warning("Deleted file: %s", path)

    def on_moved(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                logger.warning("Moved file: %s", path)
