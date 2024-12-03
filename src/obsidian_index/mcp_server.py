import asyncio
import itertools
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import mcp.server.stdio
import mcp.types as types
import pydantic
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from obsidian_index.index.encoder import Encoder
from obsidian_index.index.searcher import Searcher
from obsidian_index.logging import logging
from obsidian_index.recent_notes import find_recent_notes

logger = logging.getLogger(__name__)


def run_background_indexer(vaults: dict[str, Path], database_path: Path):
    """
    Run the indexer in a different process.
    We re-invoke "obsidian-index" with the "index" command.
    """
    assert all(vault_path.name == vault_name for vault_name, vault_path in vaults.items()), (
        "Due to the way we get the vault name from the path, "
        "the vault name must match the directory name. "
        "This may be relaxed in the future."
    )
    vault_options = itertools.chain.from_iterable(
        ["--vault", vault_path] for vault_path in vaults.values()
    )
    args = [
        sys.executable,
        sys.argv[0],
        "index",
        "--database",
        database_path,
        *vault_options,
        "--watch",
    ]
    logger.info(
        "Starting background indexer with args: %s",
        " ".join(str(arg) for arg in args),
    )
    popen = subprocess.Popen(
        args,
        # Forward stderr to the parent process
        stderr=sys.stderr,
    )
    logger.info("Started background indexer: %s", popen.pid)


def run_server(vaults: dict[str, Path], database_path: Path, background_indexer: bool = False):
    encoder = Encoder()
    server = Server("obsidian-index")

    if background_indexer:
        run_background_indexer(vaults, database_path)

    searcher = Searcher(database_path, vaults, encoder)

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        List available tools.
        Each tool specifies its arguments using JSON Schema validation.
        """
        return [
            types.Tool(
                name="search-notes",
                description="Search for relevant notes",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            )
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """
        Handle tool execution requests.
        Tools can modify server state and notify clients of changes.
        """
        if name != "search-notes":
            raise ValueError(f"Unknown tool: {name}")

        if not arguments:
            raise ValueError("Missing arguments")

        query = arguments.get("query")

        if not query:
            raise ValueError("Missing query")

        paths = searcher.search(query)

        return [
            types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=pydantic.networks.FileUrl("file://" + str(path)),
                    mimeType="text/markdown",
                    text=path.read_text(),
                ),
            )
            for path in paths
        ]

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        """
        List available resources.
        """
        resources = []
        for vault_name, vault_path in vaults.items():
            recently_changed = find_recent_notes(vault_path)
            for note_path in recently_changed:
                resources.append(
                    types.Resource(
                        uri=pydantic.networks.AnyUrl(f"obsidian://{vault_name}/{note_path}"),
                        name=note_path.with_suffix("").name,
                        description=f"{vault_name}: {note_path.parent}",
                        mimeType="text/markdown",
                    )
                )
        return resources

    @server.read_resource()
    async def handle_read_resource(uri: pydantic.networks.AnyUrl) -> str:
        """
        Read a resource.
        """
        logger.info("Reading resource: %s", uri)
        if uri.scheme != "obsidian":
            raise ValueError(f"Unsupported scheme: {uri.scheme}")

        if not uri.path:
            raise ValueError("Missing path")

        vault_name = unquote(uri.host)
        # Remove leading slash
        note_path = Path(unquote(uri.path.lstrip("/")))
        logger.info("Reading note: '%s' from vault '%s'", note_path, vault_name)
        vault_path = vaults.get(vault_name)
        if not vault_path:
            raise ValueError(f"Unknown vault: {vault_name}")

        note_path = vault_path / note_path
        if not note_path.exists():
            raise ValueError(f"Note not found: {note_path}")

        return note_path.read_text()

    async def run_server():
        # Run the server using stdin/stdout streams
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="obsidian-index",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    logger.info("Starting server")

    asyncio.run(run_server())
