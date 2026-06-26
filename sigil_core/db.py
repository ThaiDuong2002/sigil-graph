import sqlite3
from pathlib import Path

_DB_SUBPATH = ".sigil/sigil.db"

def get_db(root: Path) -> sqlite3.Connection:
    db_path = root / _DB_SUBPATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            path  TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            hash  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS symbols (
            id             INTEGER PRIMARY KEY,
            name           TEXT NOT NULL,
            kind           TEXT NOT NULL,
            file_path      TEXT NOT NULL,
            start_line     INTEGER NOT NULL,
            end_line       INTEGER NOT NULL,
            source_text    TEXT NOT NULL,
            signature_text TEXT NOT NULL,
            is_test        INTEGER NOT NULL DEFAULT 0,
            summary        TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS edges (
            caller_id  INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            callee_id  INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            call_count INTEGER NOT NULL DEFAULT 1,
            call_sites TEXT    NOT NULL DEFAULT '[]',
            PRIMARY KEY (caller_id, callee_id)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
            name,
            signature_text,
            summary,
            content=symbols,
            content_rowid=id
        );
        INSERT OR IGNORE INTO meta VALUES ('index_version', '0');
    """)
    conn.commit()
    migrate_schema(conn)


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema without dropping data."""
    existing_edges = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    if 'call_count' not in existing_edges:
        conn.execute("ALTER TABLE edges ADD COLUMN call_count INTEGER NOT NULL DEFAULT 1")
    if 'call_sites' not in existing_edges:
        conn.execute("ALTER TABLE edges ADD COLUMN call_sites TEXT NOT NULL DEFAULT '[]'")

    symbols_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols'"
    ).fetchone()
    if symbols_exists:
        existing_symbols = {row[1] for row in conn.execute("PRAGMA table_info(symbols)").fetchall()}
        if 'summary' not in existing_symbols:
            conn.execute("ALTER TABLE symbols ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            # FTS5 content table must be dropped and recreated to expose new column
            conn.execute("DROP TABLE IF EXISTS bm25_index")
            conn.executescript("""
                CREATE VIRTUAL TABLE bm25_index USING fts5(
                    name,
                    signature_text,
                    summary,
                    content=symbols,
                    content_rowid=id
                );
            """)
            conn.execute("INSERT INTO bm25_index(bm25_index) VALUES('rebuild')")

    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild FTS5 index from current symbols table (call after updating summaries)."""
    conn.execute("INSERT INTO bm25_index(bm25_index) VALUES('rebuild')")
    conn.commit()


def get_index_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()
    return int(row[0]) if row else 0

def bump_index_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'index_version'"
    )
    conn.commit()
    return get_index_version(conn)
