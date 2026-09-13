"""Entry point: python -m mcp_notes [--db PATH]."""

from __future__ import annotations

import argparse
import sys

from .server import serve
from .store import DEFAULT_DB, Store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-notes", description="MCP notes server over stdio")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite file to keep notes in, default {DEFAULT_DB}",
    )
    args = parser.parse_args(argv)

    store = Store(args.db)
    # Logs go to stderr: stdout carries the protocol and must stay clean.
    print(f"mcp-notes-server ready, db {store.path}", file=sys.stderr)
    try:
        serve(store)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
