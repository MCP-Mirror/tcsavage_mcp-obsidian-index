from collections.abc import Sequence
from pathlib import Path

import click


@click.group("obsidian-index")
def main():
    """
    CLI for Obsidian Index.
    """
    pass


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
@click.option("--reindex", is_flag=True, help="Reindex all notes.")
@click.option("--watch", is_flag=True, help="Watch for changes.")
def mcp_cmd(database_path: Path, vault_paths: Sequence[Path], reindex: bool, watch: bool):
    """
    Run the Obsidian Index MCP server.
    """
    from obsidian_index.mcp_server import run_server

    run_server(
        {vault_path.name: vault_path for vault_path in vault_paths},
        database_path,
        enqueue_all=reindex,
        watch_directories=watch,
        ingest_batch_size=8,
    )


if __name__ == "__main__":
    main()
