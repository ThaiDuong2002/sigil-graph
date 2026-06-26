from pathlib import Path
from sigil_core.db import get_db, init_schema
from sigil_core.indexer import index_project
from sigil_core.overview import generate_overview


def test_overview_contains_symbol_names(tmp_path):
    (tmp_path / "auth.py").write_text(
        "class AuthService:\n    def login(self): pass\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    md = generate_overview(conn, tmp_path)
    assert "AuthService" in md


def test_overview_contains_stats(tmp_path):
    (tmp_path / "app.py").write_text("def main(): pass\n")
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    md = generate_overview(conn, tmp_path)
    assert "symbol" in md.lower()
