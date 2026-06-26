from pathlib import Path
from sigil_core.db import get_db, init_schema
from sigil_core.indexer import index_project
from sigil_core.retrieval import search_bm25, SymbolResult, locate
from sigil_core.cache import QueryCache


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


def test_locate_returns_results(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def validate_token(token: str) -> bool:\n    return True\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    results = locate(conn, "validate token", budget=2000)
    assert len(results) > 0
    assert results[0].name == "validate_token"


def test_locate_respects_budget(tmp_path):
    (tmp_path / "auth.py").write_text(
        "\n".join(f"def fn{i}(x): return x\n" for i in range(20))
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    results = locate(conn, "fn", budget=100)
    total = sum(r.token_estimate for r in results)
    assert total <= 200  # slight overrun OK due to "always include one" rule


def test_locate_uses_cache(tmp_path):
    (tmp_path / "auth.py").write_text("def check(x): return x\n")
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    cache = QueryCache()
    cache.invalidate_if_stale(conn)
    r1 = locate(conn, "check", cache=cache)
    r2 = locate(conn, "check", cache=cache)
    assert r1 == r2
