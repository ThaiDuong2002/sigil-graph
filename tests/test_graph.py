from pathlib import Path
from symbex_core.db import get_db, init_schema
from symbex_core.indexer import index_project
from symbex_core.graph import get_callers, get_callees, get_impact

def _setup_graph(tmp_path: Path):
    (tmp_path / "tokens.py").write_text(
        "def validate_token(token: str) -> bool:\n    return len(token) == 32\n"
    )
    (tmp_path / "auth.py").write_text(
        "from tokens import validate_token\n\n"
        "def login(user_id: int, token: str) -> bool:\n"
        "    return validate_token(token)\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    return conn

def test_get_callers_finds_caller(tmp_path):
    conn = _setup_graph(tmp_path)
    results = get_callers(conn, "validate_token")
    names = [r.name for r in results]
    assert "login" in names

def test_get_callees_finds_callee(tmp_path):
    conn = _setup_graph(tmp_path)
    results = get_callees(conn, "login")
    names = [r.name for r in results]
    assert "validate_token" in names

def test_depth1_results_are_signature_only(tmp_path):
    conn = _setup_graph(tmp_path)
    results = get_callees(conn, "login", depth=1)
    for r in results:
        assert r.is_signature_only
        assert r.text.endswith(': ...')

def test_get_impact_returns_count(tmp_path):
    conn = _setup_graph(tmp_path)
    impact = get_impact(conn, "validate_token")
    assert impact["count"] >= 1
    assert "login" in impact["callers"]

def test_get_callers_no_callers_returns_empty(tmp_path):
    conn = _setup_graph(tmp_path)
    results = get_callers(conn, "login")  # nothing calls login
    assert results == []
