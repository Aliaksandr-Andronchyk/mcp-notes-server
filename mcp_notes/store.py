"""SQLite storage for notes: create, read, update, delete, full-text search, tags."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("MCP_NOTES_DB", "~/.mcp-notes/notes.db")).expanduser()

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL DEFAULT '',
    created   REAL NOT NULL,
    updated   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);

CREATE INDEX IF NOT EXISTS tags_by_tag ON tags(tag);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, body, content='notes', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO notes_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
"""

TAG_RE = re.compile(r"^[\w][\w/.-]*$", re.UNICODE)


class NoteNotFound(Exception):
    """Raised when an id does not match any note."""


class BadInput(Exception):
    """Raised on input the caller can fix: empty title, malformed tag, empty query."""


@dataclass
class Note:
    id: int
    title: str
    body: str
    tags: list[str]
    created: float
    updated: float
    snippet: str | None = None

    def as_dict(self) -> dict:
        out = {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "tags": self.tags,
            "created": self.created,
            "updated": self.updated,
        }
        if self.snippet is not None:
            out["snippet"] = self.snippet
        return out


def normalize_tags(raw) -> list[str]:
    """Lowercase, strip a leading '#', drop duplicates, keep the given order."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [chunk for chunk in re.split(r"[,\s]+", raw) if chunk]
    if not isinstance(raw, list):
        raise BadInput("tags must be a list of strings or a comma separated string")

    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise BadInput("tags must be strings")
        tag = item.strip().lstrip("#").lower()
        if not tag:
            continue
        if not TAG_RE.match(tag):
            raise BadInput(f"bad tag {item!r}: letters, digits, '_', '-', '.', '/' only")
        if tag not in seen:
            seen.append(tag)
    return seen


def fts_query(text: str) -> str:
    """Turn user words into a safe FTS5 query: every word a prefix match, all required.

    Quoting each token keeps FTS5 operators ('OR', 'NEAR', '*', ':') out of the parser,
    so a search string is never able to error out or reach beyond matching.
    """
    tokens = [t for t in re.split(r"\W+", text, flags=re.UNICODE) if t]
    if not tokens:
        raise BadInput("empty search query")
    return " AND ".join(f'"{t}"*' for t in tokens)


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path).expanduser()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # writes

    def add(self, title: str, body: str = "", tags=None) -> Note:
        title = (title or "").strip()
        if not title:
            raise BadInput("title is required")
        tags = normalize_tags(tags)
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO notes (title, body, created, updated) VALUES (?, ?, ?, ?)",
            (title, body or "", now, now),
        )
        note_id = int(cur.lastrowid)
        self._set_tags(note_id, tags)
        self.db.commit()
        return self.get(note_id)

    def update(self, note_id: int, title=None, body=None, tags=None) -> Note:
        current = self.get(note_id)
        new_title = current.title if title is None else (title or "").strip()
        if not new_title:
            raise BadInput("title cannot be emptied")
        new_body = current.body if body is None else body
        self.db.execute(
            "UPDATE notes SET title = ?, body = ?, updated = ? WHERE id = ?",
            (new_title, new_body, time.time(), note_id),
        )
        if tags is not None:
            self.db.execute("DELETE FROM tags WHERE note_id = ?", (note_id,))
            self._set_tags(note_id, normalize_tags(tags))
        self.db.commit()
        return self.get(note_id)

    def delete(self, note_id: int) -> None:
        self.get(note_id)
        self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.db.commit()

    def _set_tags(self, note_id: int, tags: list[str]) -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO tags (note_id, tag) VALUES (?, ?)",
            [(note_id, tag) for tag in tags],
        )

    # reads

    def get(self, note_id: int) -> Note:
        row = self.db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise NoteNotFound(f"no note with id {note_id}")
        return self._note(row)

    def list(self, tag: str | None = None, limit: int = 20, offset: int = 0) -> list[Note]:
        if tag:
            wanted = normalize_tags([tag])
            if not wanted:
                raise BadInput("empty tag")
            rows = self.db.execute(
                "SELECT n.* FROM notes n JOIN tags t ON t.note_id = n.id "
                "WHERE t.tag = ? ORDER BY n.updated DESC LIMIT ? OFFSET ?",
                (wanted[0], limit, offset),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM notes ORDER BY updated DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._note(row) for row in rows]

    def search(self, query: str, tag: str | None = None, limit: int = 20) -> list[Note]:
        match = fts_query(query)
        sql = (
            "SELECT n.*, snippet(notes_fts, -1, '[', ']', '...', 12) AS snip "
            "FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid "
            "WHERE notes_fts MATCH ? "
        )
        params: list = [match]
        if tag:
            wanted = normalize_tags([tag])
            if not wanted:
                raise BadInput("empty tag")
            sql += "AND n.id IN (SELECT note_id FROM tags WHERE tag = ?) "
            params.append(wanted[0])
        sql += "ORDER BY bm25(notes_fts) LIMIT ?"
        params.append(limit)
        rows = self.db.execute(sql, params).fetchall()
        return [self._note(row, snippet=row["snip"]) for row in rows]

    def tags(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT tag, COUNT(*) AS count FROM tags GROUP BY tag ORDER BY count DESC, tag"
        ).fetchall()
        return [{"tag": row["tag"], "count": row["count"]} for row in rows]

    def _note(self, row: sqlite3.Row, snippet: str | None = None) -> Note:
        tags = [
            r["tag"]
            for r in self.db.execute(
                "SELECT tag FROM tags WHERE note_id = ? ORDER BY tag", (row["id"],)
            )
        ]
        return Note(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            tags=tags,
            created=row["created"],
            updated=row["updated"],
            snippet=snippet,
        )
