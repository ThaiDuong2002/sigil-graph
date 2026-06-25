import sqlite3
from pathlib import Path
import pytest
from symbex_core.db import get_db, init_schema, get_index_version, bump_index_version

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

def test_get_db_creates_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    conn = get_db(root)
    assert (root / ".symbex" / "symbex.db").exists()
