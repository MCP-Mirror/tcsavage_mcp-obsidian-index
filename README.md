# Obsidian Index MCP server

An MCP server that provides a semantic search over an Obsidian vault and exposes recent notes as resources.

## Components

### Resources

The server exposes recently modified notes in your vaults as resources to MCP clients.
- Notes are addressed by an `obsidian://<VAULT_NAME>/<NOTE_PATH>` URL scheme
- Notes have the `text/markdown` media type

### Tools

The server implements one tool:
- `search-notes`: Performs semantic search over indexed notes

## Run the server

```bash
uv run obsidian-index mcp --vault <VAULT_PATH> --database <DATABASE_PATH> --reindex --watch
```

- `--vault`: Path to the Obsidian vault (can be specified multiple times)
- `--database`: Path to the local database file (will be created if it doesn't exist)
- `--reindex`: Reindex all notes in the vault (you probably want this every time right now)
- `--watch`: Watch for changes in the vault and update the index accordingly

## Quickstart

### Install

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

<details>
  <summary>Development/Unpublished Servers Configuration</summary>
  ```
  "mcpServers": {
    "obsidian-index": {
      "command": "uv",
      "args": [
        "--directory",
        "<PATH_TO_PROJECT>",
        "run",
        "obsidian-index",
        "--database",
        "<PATH_TO_DATABASE>",
        "--vault",
        "<PATH_TO_VAULT>",
        "--reindex",
        "--watch"
      ]
    }
  }
  ```
</details>

<details>
  <summary>Published Servers Configuration</summary>
  ```
  "mcpServers": {
    "obsidian-index": {
      "command": "uvx",
      "args": [
        "obsidian-index",
        "--database",
        "<PATH_TO_DATABASE>",
        "--vault",
        "<PATH_TO_VAULT>",
        "--reindex",
        "--watch"
      ]
    }
  }
  ```
</details>

## Development

### Building and Publishing

To prepare the package for distribution:

1. Sync dependencies and update lockfile:
```bash
uv sync
```

2. Build package distributions:
```bash
uv build
```

This will create source and wheel distributions in the `dist/` directory.

3. Publish to PyPI:
```bash
uv publish
```

Note: You'll need to set PyPI credentials via environment variables or command flags:
- Token: `--token` or `UV_PUBLISH_TOKEN`
- Or username/password: `--username`/`UV_PUBLISH_USERNAME` and `--password`/`UV_PUBLISH_PASSWORD`

### Debugging

Since MCP servers run over stdio, debugging can be challenging. For the best debugging
experience, we strongly recommend using the [MCP Inspector](https://github.com/modelcontextprotocol/inspector).


You can launch the MCP Inspector via [`npm`](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) with this command:

```bash
npx @modelcontextprotocol/inspector uv --directory <PATH_TO_PROJECT> run obsidian-index
```


Upon launching, the Inspector will display a URL that you can access in your browser to begin debugging.