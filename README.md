# mcp-notes-server

A small MCP server that gives an AI agent a notebook: write notes, search them full text,
organise them with tags. Written in plain Python 3.11, standard library only, no dependencies
to install and nothing to run in the background.

## Why

An agent forgets everything between sessions. Files work for long documents, but not for the
hundreds of small facts that pile up during work: a decision, a hostname, why an approach was
dropped. This server keeps them in one SQLite file and makes them findable in one tool call.

It is also a compact, readable reference of what a Model Context Protocol server actually is:
JSON-RPC 2.0 over stdin and stdout, an `initialize` handshake, and a list of typed tools.

## Install

```sh
git clone https://github.com/Aliaksandr-Andronchyk/mcp-notes-server.git
cd mcp-notes-server
python3 -m mcp_notes --help
```

Python 3.11 or newer, with SQLite compiled with FTS5 (the default on macOS and Debian).

## Connect to Claude Code

One line:

```sh
claude mcp add notes -- python3 -m mcp_notes
```

Run it from the clone, or add `--db ~/.mcp-notes/notes.db` and use an absolute path to
`python3` if you launch from elsewhere. The equivalent entry in `.mcp.json` or
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "notes": {
      "command": "python3",
      "args": ["-m", "mcp_notes", "--db", "~/.mcp-notes/notes.db"],
      "cwd": "/path/to/mcp-notes-server"
    }
  }
}
```

Check it with `claude mcp list`, then ask the agent to "save a note about X" or
"search my notes for X".

## Tools

| Tool | What it does |
| --- | --- |
| `add_note` | Save a note: `title`, optional `body`, optional `tags`. |
| `search_notes` | Full text search over title and body, optional `tag` filter. Returns snippets. |
| `list_notes` | Recently changed notes first, optional `tag` filter, `limit` and `offset`. |
| `get_note` | Read one note in full by `id`. |
| `update_note` | Change `title`, `body` or `tags`. Omitted fields stay as they are. |
| `delete_note` | Delete by `id`. |
| `list_tags` | Every tag in use with the number of notes carrying it. |

Search treats each word as a prefix, so `migra` finds `migrations`, and requires all words to
match. Search text is tokenized and quoted before it reaches SQLite, so FTS5 operators typed by
a user are matched as ordinary words instead of changing the query. Tags are lowercased, a
leading `#` is stripped, and duplicates are dropped.

## Storage

One SQLite file, `~/.mcp-notes/notes.db` by default, overridden by `--db` or the `MCP_NOTES_DB`
environment variable. Notes live in an ordinary table; an FTS5 index is kept in sync by triggers,
so writes through any path stay searchable. Back it up by copying the file.

## Run by hand

Useful for debugging without a client attached:

```sh
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add_note","arguments":{"title":"hello","tags":["demo"]}}}' \
  | python3 -m mcp_notes --db /tmp/notes.db
```

Logs go to stderr, because stdout carries the protocol and has to stay clean.

## Tests

```sh
pip install pytest
python3 -m pytest tests -q
```

31 tests covering storage, search behaviour, the JSON-RPC layer and a full stdio session.

## Licence

MIT.
