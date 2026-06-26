import sqlite3
from pathlib import Path
import tree_sitter_typescript  # noqa: import check
from sigil_core.indexer import Symbol, extract_symbols_python, extract_symbols_typescript, index_project, iter_source_files
from sigil_core.db import get_db, init_schema, get_index_version

FIXTURE = Path(__file__).parent / "fixtures" / "sample.py"
FIXTURE_TS = Path(__file__).parent / "fixtures" / "sample.ts"

def test_extracts_top_level_function():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    names = [s.name for s in symbols]
    assert "greet" in names

def test_extracts_class():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    names = [s.name for s in symbols]
    assert "AuthService" in names

def test_extracts_methods_with_qualified_name():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    names = [s.name for s in symbols]
    assert "AuthService.login" in names
    assert "AuthService.logout" in names

def test_symbol_has_correct_line_range():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    greet = next(s for s in symbols if s.name == "greet")
    assert greet.start_line == 2
    assert greet.end_line == 3

def test_symbol_source_text_matches():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    greet = next(s for s in symbols if s.name == "greet")
    assert 'def greet' in greet.source_text
    assert 'return f"Hello' in greet.source_text

def test_signature_text_is_first_line_with_ellipsis():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "sample.py", is_test=False)
    greet = next(s for s in symbols if s.name == "greet")
    assert greet.signature_text == "def greet(name: str) -> str: ..."

def test_is_test_flag_propagated():
    source = FIXTURE.read_text()
    symbols = extract_symbols_python(source, "tests/sample.py", is_test=True)
    assert all(s.is_test for s in symbols)


def test_ts_extracts_top_level_function():
    source = FIXTURE_TS.read_text()
    symbols = extract_symbols_typescript(source, "sample.ts", is_test=False)
    names = [s.name for s in symbols]
    assert "greet" in names


def test_ts_extracts_class():
    source = FIXTURE_TS.read_text()
    symbols = extract_symbols_typescript(source, "sample.ts", is_test=False)
    names = [s.name for s in symbols]
    assert "AuthService" in names


def test_ts_extracts_methods_with_qualified_name():
    source = FIXTURE_TS.read_text()
    symbols = extract_symbols_typescript(source, "sample.ts", is_test=False)
    names = [s.name for s in symbols]
    assert "AuthService.login" in names
    assert "AuthService.logout" in names


# Integration tests for iter_source_files and index_project

def test_iter_source_files_finds_py_and_ts(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.ts").write_text("const x = 1;")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("")
    files = list(iter_source_files(tmp_path))
    paths = [str(f) for f in files]
    assert any("a.py" in p for p in paths)
    assert any("b.ts" in p for p in paths)
    assert not any("node_modules" in p for p in paths)


def test_index_project_stores_symbols(tmp_path):
    (tmp_path / "app.py").write_text(
        "def hello(name: str) -> str:\n    return name\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    stats = index_project(tmp_path, conn)
    assert stats["symbols"] >= 1
    row = conn.execute("SELECT name FROM symbols WHERE name='hello'").fetchone()
    assert row is not None


def test_index_project_incremental_skips_unchanged(tmp_path):
    (tmp_path / "app.py").write_text("def foo(): pass\n")
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    v1 = get_index_version(conn)
    index_project(tmp_path, conn)  # nothing changed
    v2 = get_index_version(conn)
    assert v1 == v2  # version unchanged, file skipped


def test_index_project_reindexes_changed_file(tmp_path):
    py_file = tmp_path / "app.py"
    py_file.write_text("def foo(): pass\n")
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)

    py_file.write_text("def foo(): pass\ndef bar(): pass\n")
    index_project(tmp_path, conn)

    rows = conn.execute("SELECT name FROM symbols WHERE file_path LIKE '%app.py'").fetchall()
    names = [r[0] for r in rows]
    assert "bar" in names
