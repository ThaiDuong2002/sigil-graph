import sqlite3
from pathlib import Path
import pytest
from symbex_core.db import get_db, init_schema, migrate_schema, get_index_version, bump_index_version

def test_init_schema_creates_tables(tmp_path):
    conn = get_db(tmp_path)
    init_schema(conn)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' OR type='shadow'"
    )}
    assert 'files' in tables
    assert 'symbols' in tables
    assert 'edges' in tables
    assert 'meta' in tables

def test_index_version_starts_at_zero(tmp_path):
    conn = get_db(tmp_path)
    init_schema(conn)
    assert get_index_version(conn) == 0

def test_bump_index_version_increments(tmp_path):
    conn = get_db(tmp_path)
    init_schema(conn)
    v1 = bump_index_version(conn)
    v2 = bump_index_version(conn)
    assert v1 == 1
    assert v2 == 2

def test_migrate_schema_adds_columns_to_old_db(tmp_path):
    # Simulate a pre-migration database missing call_count / call_sites
    conn = get_db(tmp_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS edges (
            caller_id INTEGER NOT NULL,
            callee_id INTEGER NOT NULL,
            PRIMARY KEY (caller_id, callee_id)
        );
    """)
    conn.commit()
    migrate_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    assert 'call_count' in cols
    assert 'call_sites' in cols


def test_migrate_schema_idempotent(tmp_path):
    conn = get_db(tmp_path)
    init_schema(conn)
    migrate_schema(conn)  # second call should not raise
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)").fetchall()}
    assert 'call_count' in cols


def test_get_db_creates_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    conn = get_db(root)
    assert (root / ".symbex" / "symbex.db").exists()
