import asyncio
from pathlib import Path
from urllib.parse import unquote

import mcp.server.stdio
import mcp.types as types
import pydantic
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from obsidian_index.background_worker import BaseController
from obsidian_index.index.messages import SearchRequestMessage
from obsidian_index.index.worker import Worker
from obsidian_index.logger import logging
from obsidian_index.recent_notes import find_recent_notes

logger = logging.getLogger(__name__)


def run_server(
    vaults: dict[str, Path],
    database_path: Path,
    enqueue_all: bool = False,
    watch_directories: bool = False,
    ingest_batch_size: int = 32,
):
    # encoder = Encoder()
    server = Server("obsidian-index")
    worker = Worker(
        database_path,
        vaults,
        enqueue_all=enqueue_all,
        watch_directories=watch_directories,
        ingest_batch_size=ingest_batch_size,
    )
    worker_controller = BaseController(worker)

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

        resp = await worker_controller.request(SearchRequestMessage(query))

        return [
            types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=pydantic.networks.FileUrl("file://" + str(path)),
                    mimeType="text/markdown",
                    text=path.read_text(),
                ),
            )
            for path in resp.paths
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
        worker_controller.start()
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

        worker_controller.stop()

    logger.info("Starting server")

    asyncio.run(run_server())
