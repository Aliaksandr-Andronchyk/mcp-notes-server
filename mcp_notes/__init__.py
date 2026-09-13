"""mcp-notes-server: notes, search and tags for MCP clients."""

from .server import Server, serve
from .store import Note, Store

__version__ = "1.0.0"
__all__ = ["Note", "Server", "Store", "serve", "__version__"]
