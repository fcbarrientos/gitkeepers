"""SQLite storage: one file, numbered migrations, optional vector search"""
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from core import config


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    # FastAPI may open a request's connection in one worker thread and use it in
    # another; each connection still serves only one request at a time.
    conn = sqlite3.connect(
        db_path or config.DB_PATH, timeout=config.DB_BUSY_TIMEOUT_SECONDS, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply any unapplied NNN_name.sql files in order. Returns names applied."""
    migrations_dir = migrations_dir or config.MIGRATIONS_DIR
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_version")}
    applied = []
    for f in sorted(migrations_dir.glob("*.sql")):
        m = re.match(r"(\d+)_", f.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in done:
            continue
        with conn:  # one transaction per migration
            conn.executescript(f"BEGIN; {f.read_text()}")
            conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)",
                         (version, f.name))
        applied.append(f.name)
    return applied


def enable_vectors(conn: sqlite3.Connection, dim: int) -> None:
    """Load sqlite-vec and create the embeddings table (dim depends on your embedding model)."""
    import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
    )


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
