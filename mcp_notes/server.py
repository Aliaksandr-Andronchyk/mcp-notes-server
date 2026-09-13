"""MCP server over stdio: JSON-RPC 2.0, six note tools, no third party dependencies.

Speaks the Model Context Protocol handshake (initialize / tools/list / tools/call)
well enough for Claude Code and any other MCP client that talks stdio.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .store import BadInput, NoteNotFound, Store

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_INFO = {"name": "mcp-notes-server", "version": "1.0.0"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOLS = [
    {
        "name": "add_note",
        "description": "Save a new note with a title, an optional body and optional tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title, required."},
                "body": {"type": "string", "description": "Note text."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags, lowercased automatically, a leading # is stripped.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_notes",
        "description": "Full text search over titles and bodies, newest ranking first, "
        "optionally narrowed to one tag. Every word is a prefix match.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for."},
                "tag": {"type": "string", "description": "Only notes carrying this tag."},
                "limit": {"type": "integer", "description": "Max results, default 20."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_notes",
        "description": "List notes by last change, optionally filtered by tag.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results, default 20."},
                "offset": {"type": "integer", "description": "Skip this many, default 0."},
            },
        },
    },
    {
        "name": "get_note",
        "description": "Read one note in full by its id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "update_note",
        "description": "Change title, body or tags of a note. Omitted fields stay as they are.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_note",
        "description": "Delete a note by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "list_tags",
        "description": "All tags in use with the number of notes carrying each.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _require_int(args: dict, key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadInput(f"{key} must be an integer")
    return value


def _limit(args: dict, key: str, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BadInput(f"{key} must be a non negative integer")
    return min(value, 200)


class Server:
    def __init__(self, store: Store):
        self.store = store
        self.tools = {
            "add_note": self._add_note,
            "search_notes": self._search_notes,
            "list_notes": self._list_notes,
            "get_note": self._get_note,
            "update_note": self._update_note,
            "delete_note": self._delete_note,
            "list_tags": self._list_tags,
        }

    # tools

    def _add_note(self, args: dict) -> dict:
        note = self.store.add(args.get("title", ""), args.get("body", ""), args.get("tags"))
        return {"note": note.as_dict()}

    def _search_notes(self, args: dict) -> dict:
        query = args.get("query")
        if not isinstance(query, str):
            raise BadInput("query must be a string")
        found = self.store.search(query, args.get("tag"), _limit(args, "limit", 20))
        return {"count": len(found), "notes": [n.as_dict() for n in found]}

    def _list_notes(self, args: dict) -> dict:
        found = self.store.list(
            args.get("tag"), _limit(args, "limit", 20), _limit(args, "offset", 0)
        )
        return {"count": len(found), "notes": [n.as_dict() for n in found]}

    def _get_note(self, args: dict) -> dict:
        return {"note": self.store.get(_require_int(args, "id")).as_dict()}

    def _update_note(self, args: dict) -> dict:
        note = self.store.update(
            _require_int(args, "id"), args.get("title"), args.get("body"), args.get("tags")
        )
        return {"note": note.as_dict()}

    def _delete_note(self, args: dict) -> dict:
        note_id = _require_int(args, "id")
        self.store.delete(note_id)
        return {"deleted": note_id}

    def _list_tags(self, args: dict) -> dict:
        return {"tags": self.store.tags()}

    # protocol

    def handle(self, request: dict) -> dict | None:
        """Return a JSON-RPC response, or None for a notification."""
        req_id = request.get("id")
        method = request.get("method")
        is_notification = "id" not in request

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            if is_notification:
                return None
            return error(req_id, INVALID_REQUEST, "not a JSON-RPC 2.0 request")

        params = request.get("params") or {}
        if not isinstance(params, dict):
            return None if is_notification else error(req_id, INVALID_PARAMS, "params must be an object")

        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif method == "ping":
                result = {}
            elif method in ("notifications/initialized", "notifications/cancelled"):
                return None
            else:
                if is_notification:
                    return None
                return error(req_id, METHOD_NOT_FOUND, f"unknown method {method}")
        except BadInput as exc:
            return None if is_notification else error(req_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crash here would kill the session
            return None if is_notification else error(req_id, INTERNAL_ERROR, str(exc))

        return None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise BadInput("arguments must be an object")
        tool = self.tools.get(name)
        if tool is None:
            raise BadInput(f"unknown tool {name!r}")

        # A tool failure is reported inside the result, not as a protocol error:
        # that is what lets the model read the message and try again.
        try:
            payload: Any = tool(args)
        except (BadInput, NoteNotFound) as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return {"content": [{"type": "text", "text": text}], "isError": False}


def error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve(store: Store, stdin=None, stdout=None) -> None:
    """Read one JSON object per line, answer on one line. Ends on EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    server = Server(store)

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            write(stdout, error(None, PARSE_ERROR, f"bad JSON: {exc}"))
            continue
        if not isinstance(request, dict):
            write(stdout, error(None, INVALID_REQUEST, "request must be an object"))
            continue
        response = server.handle(request)
        if response is not None:
            write(stdout, response)


def write(stdout, message: dict) -> None:
    stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    stdout.flush()
