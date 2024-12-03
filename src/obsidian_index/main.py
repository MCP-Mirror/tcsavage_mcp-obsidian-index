import time
from collections.abc import Sequence
from pathlib import Path

import click


@click.group("obsidian-index")
def main():
    """
    CLI for Obsidian Index.
    """
    pass


@main.command("index")
@click.option(
    "--vault",
    "-v",
    "vault_paths",
    multiple=True,
    help="Vault to index.",
    required=True,
    type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
)
@click.option(
    "--database",
    "-d",
    "database_path",
    help="Path to the database.",
    required=True,
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
)
@click.option("--watch", "-w", is_flag=True, help="Watch for changes.")
@click.option("--ingest-batch-size", default=32, help="Ingest batch size.", type=int)
@click.option("--model-batch-size", default=16, help="Model batch size.", type=int)
def index_cmd(
    vault_paths: Sequence[Path],
    database_path: Path,
    watch: bool,
    ingest_batch_size: int,
    model_batch_size: int,
):
    """
    Index notes in an Obsidian vault.
    """
    from obsidian_index.index.encoder import Encoder
    from obsidian_index.index.indexer import Indexer

    encoder = Encoder()
    indexer = Indexer(
        database_path,
        {vault_path.name: vault_path for vault_path in vault_paths},
        encoder,
        watch=watch,
        ingest_batch_size=ingest_batch_size,
        model_batch_size=model_batch_size,
    )
    time_start = time.time()
    indexer.run_ingestor(stop_when_done=not watch)
    time_stop = time.time()
    print(f"Indexing took {time_stop - time_start:.2f} seconds.")


@main.command("search")
@click.argument("query")
@click.option(
    "--database",
    "-d",
    "database_path",
    help="Path to the database.",
    required=True,
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
)
@click.option(
    "--vault",
    "-v",
    "vault_paths",
    multiple=True,
    help="Vault to search.",
    required=True,
    type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
)
@click.option(
    "--top-k",
    default=10,
    help="Number of results to return.",
    type=int,
)
def search_cmd(query: str, database_path: Path, vault_paths: Sequence[Path], top_k: int):
    """
    Search for notes in an Obsidian vault.
    """
    from obsidian_index.index.encoder import Encoder
    from obsidian_index.index.searcher import Searcher

    encoder = Encoder()
    searcher = Searcher(
        database_path, {vault_path.name: vault_path for vault_path in vault_paths}, encoder
    )
    time_start = time.time()
    paths = searcher.search(query, top_k=top_k)
    time_stop = time.time()
    print(f"Search took {time_stop - time_start:.2f} seconds.")
    for path in paths:
        print(path)


@main.command("mcp")
@click.option(
    "--database",
    "-d",
    "database_path",
    help="Path to the database.",
    required=True,
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
)
@click.option(
    "--vault",
    "-v",
    "vault_paths",
    multiple=True,
    help="Vault to index.",
    required=True,
    type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
)
@click.option("--background-indexer", is_flag=True, help="Run the background indexer.")
def mcp_cmd(database_path: Path, vault_paths: Sequence[Path], background_indexer: bool):
    """
    Run the Obsidian Index MCP server.
    """
    from obsidian_index.mcp_server import run_server

    run_server(
        {vault_path.name: vault_path for vault_path in vault_paths},
        database_path,
        background_indexer,
    )


if __name__ == "__main__":
    main()
