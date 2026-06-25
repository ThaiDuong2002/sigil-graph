from pathlib import Path
from symbex_core.db import get_db, init_schema
from symbex_core.indexer import index_project
from symbex_core.retrieval import search_bm25, SymbolResult


def _setup(tmp_path: Path):
    (tmp_path / "auth.py").write_text(
        "def validate_token(token: str) -> bool:\n    return len(token) == 32\n\n"
        "def refresh_token(user_id: int, token: str) -> str:\n    return 'new'\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    return conn


def test_search_returns_relevant_symbol(tmp_path):
    conn = _setup(tmp_path)
    results = search_bm25(conn, "validate token", limit=5)
    names = [r.name for r in results]
    assert "validate_token" in names


def test_search_returns_symbol_result_type(tmp_path):
    conn = _setup(tmp_path)
    results = search_bm25(conn, "refresh token", limit=5)
    assert len(results) > 0
    r = results[0]
    assert isinstance(r, SymbolResult)
    assert r.file_path.endswith("auth.py")
    assert r.start_line > 0
    assert r.token_estimate > 0


def test_search_empty_index_returns_empty(tmp_path):
    conn = get_db(tmp_path)
    init_schema(conn)
    results = search_bm25(conn, "anything", limit=5)
    assert results == []
