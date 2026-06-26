import pytest
from pathlib import Path
from sigil_core.db import get_db, init_schema
from sigil_core.indexer import index_project
from sigil_mcp.server import (
    _result_to_dict,
    _locate_symbols,
    _get_symbol,
    _get_callers_result,
    _get_callees_result,
    _preview_symbols,
    _get_impact_result,
    _run_index,
    _get_tests,
)


@pytest.fixture
def indexed_db(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login(user: str) -> bool:\n    return True\n\n"
        "def validate(user: str) -> bool:\n    return bool(user)\n"
    )
    (tmp_path / "auth_test.py").write_text(
        "def test_login_ok():\n    assert login('alice') is True\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    return conn, tmp_path


def test_result_to_dict_fields(indexed_db):
    conn, root = indexed_db
    results = _locate_symbols(conn, "login")
    assert len(results["symbols"]) > 0
    s = results["symbols"][0]
    for field in ("name", "kind", "file_path", "start_line", "end_line",
                  "text", "is_signature_only", "token_estimate", "score"):
        assert field in s


def test_get_symbol_found(indexed_db):
    conn, root = indexed_db
    result = _get_symbol(conn, "login")
    assert result["name"] == "login"
    assert result["kind"] == "function"
    assert "def login" in result["text"]


def test_get_symbol_not_found(indexed_db):
    conn, root = indexed_db
    result = _get_symbol(conn, "nonexistent_xyz")
    assert "error" in result


def test_locate_symbols_returns_structure(indexed_db):
    conn, root = indexed_db
    result = _locate_symbols(conn, "login")
    assert "symbols" in result
    assert "total_tokens" in result
    assert isinstance(result["total_tokens"], int)


def test_preview_excludes_full_text(indexed_db):
    conn, root = indexed_db
    result = _preview_symbols(conn, "login")
    assert "symbols" in result
    assert "total_tokens" in result
    # preview items must NOT include full source text
    for s in result["symbols"]:
        assert "text" not in s
        assert "token_estimate" in s
        assert "score" in s


def test_get_callers_result_structure(indexed_db):
    conn, root = indexed_db
    result = _get_callers_result(conn, "login")
    assert "name" in result
    assert "callers" in result
    assert "count" in result
    assert result["name"] == "login"
    assert isinstance(result["callers"], list)


def test_get_callees_result_structure(indexed_db):
    conn, root = indexed_db
    result = _get_callees_result(conn, "login")
    assert "name" in result
    assert "callees" in result
    assert "count" in result


def test_get_impact_result_structure(indexed_db):
    conn, root = indexed_db
    result = _get_impact_result(conn, "login")
    assert "symbol" in result
    assert "caller_count" in result
    assert "callers" in result
    assert isinstance(result["callers"], list)


def test_run_index_returns_stats(tmp_path):
    (tmp_path / "foo.py").write_text("def bar(): pass\n")
    stats = _run_index(tmp_path)
    assert stats["symbols"] >= 1
    assert stats["files"] >= 1
    assert "edges" in stats


def test_get_tests_finds_test_symbols(indexed_db):
    conn, root = indexed_db
    result = _get_tests(conn, "login")
    assert "name" in result
    assert "tests" in result
    assert "count" in result
    # test_login_ok mentions login in its body
    assert any("login" in t["text"] for t in result["tests"])
