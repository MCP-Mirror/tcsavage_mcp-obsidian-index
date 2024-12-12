from multiprocessing import Queue
from pathlib import Path
from queue import Empty as QueueEmpty

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from obsidian_index.background_worker import BaseWorker
from obsidian_index.index.database import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.index.indexer import Indexer
from obsidian_index.index.messages import IndexMessage, SearchRequestMessage, SearchResponseMessage
from obsidian_index.index.searcher import Searcher
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)


class Worker(BaseWorker[SearchRequestMessage, SearchResponseMessage]):
    database_path: Path
    vaults: dict[str, Path]
    ingest_batch_size: int
    enqueue_all: bool
    watch_directories: bool

    database: Database
    indexer: Indexer
    searcher: Searcher
    ingest_queue: Queue
    directory_watchers: list["DirectoryWatcher"]

    def __init__(
        self,
        database_path: Path,
        vaults: dict[str, Path],
        ingest_batch_size: int = 8,
        enqueue_all: bool = False,
        watch_directories: bool = False,
    ):
        super().__init__()
        self.database_path = database_path
        self.vaults = vaults
        self.ingest_batch_size = ingest_batch_size
        self.enqueue_all = enqueue_all
        self.watch_directories = watch_directories

    def initialize(self):
        self.database = Database(self.database_path)
        encoder = Encoder()
        self.indexer = Indexer(self.database, self.vaults, encoder)
        self.searcher = Searcher(self.database, self.vaults, encoder)
        self.ingest_queue = Queue()

        if self.enqueue_all:
            self.enqueue_all_vaults()

        if self.watch_directories:
            self.directory_watchers = [
                DirectoryWatcher(self, vault_name, root, recursive=True)
                for vault_name, root in self.vaults.items()
            ]
            for watcher in self.directory_watchers:
                watcher.start()

    def enqueue_all_vaults(self):
        for vault_name, vault_path in self.vaults.items():
            self.enqueue_vault(vault_name, vault_path)

    def enqueue_vault(self, vault_name: str, vault_path: Path):
        for path in vault_path.rglob("*.md"):
            self.ingest_queue.put(IndexMessage(vault_name, path))

    def enqueue_path_for_ingestion(self, vault_name: str, path: Path):
        # FIXME: Create a proper API for this
        with self._control.work_available:
            self.ingest_queue.put(IndexMessage(vault_name, path))
            self._control.work_available.notify_all()

    def process_message(self, message: SearchRequestMessage) -> SearchResponseMessage:
        paths = self.searcher.search(message.query)
        return SearchResponseMessage(paths=paths)

    def default_work_available(self) -> bool:
        return not self.ingest_queue.empty()

    def default_work(self):
        batch: list[tuple[str, Path]] = []
        for _ in range(self.ingest_batch_size):
            try:
                message = self.ingest_queue.get_nowait()
            except QueueEmpty:
                break
            batch.append((message.vault_name, message.path))
        self.indexer.ingest_paths(batch)


class DirectoryWatcher:
    """
    A class to watch directory changes and trigger callbacks on file events.
    """

    vault_name: str
    directory: Path
    worker: Worker
    recursive: bool

    def __init__(self, worker: Worker, vault_name: str, directory: Path, recursive: bool = False):
        self.worker = worker
        self.vault_name = vault_name
        self.directory = Path(directory)
        self.recursive = recursive
        self.observer = Observer()

    def start(self) -> None:
        event_handler = _FSEventHandler(self.worker, self.vault_name, self.directory)
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
        logger.info("Starting directory watcher for %s", self.directory)
        self.observer.start()

    def stop(self) -> None:
        logger.info("Stopping directory watcher for %s", self.directory)
        self.observer.stop()
        self.observer.join()


class _FSEventHandler(FileSystemEventHandler):
    """
    Internal event handler class to process filesystem events.
    """

    vault_name: str
    directory: Path
    worker: Worker

    def __init__(self, worker: Worker, vault_name: str, directory: Path):
        self.worker = worker
        self.vault_name = vault_name
        self.directory = directory
        super().__init__()

    def on_created(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                logger.info("Created file: %s", path)
                self.worker.enqueue_path_for_ingestion(self.vault_name, path.resolve())

    def on_modified(self, event):
        if not event.is_directory:
            assert isinstance(event.src_path, str)
            path = Path(event.src_path)
            if path.is_file() and path.suffix == ".md":
                logger.info("Modified file: %s", path)
                self.worker.enqueue_path_for_ingestion(self.vault_name, path.resolve())

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


if __name__ == "__main__":
    import asyncio

    from obsidian_index.background_worker import BaseController

    async def main():
        worker = Worker(
            Path("text_index2.db"),
            {"Brain": Path("/Users/tom.savage/Documents/Brain")},
            ingest_batch_size=32,
            enqueue_all=True,
            watch_directories=True,
        )
        controller = BaseController(worker)
        controller.start()

        try:
            print("Sleeping for 5 minutes...")
            await asyncio.sleep(300)
            print("Waking up...")
            # Send a request and await its result
            response = await controller.request(SearchRequestMessage("haskell"))
            print("Search response paths:")
            for path in response.paths:
                print(path)

            print("Sleeping for 10 seconds...")
            await asyncio.sleep(10)
            print("Waking up...")

        finally:
            controller.stop()

    asyncio.run(main())
