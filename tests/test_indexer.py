from pathlib import Path
import tree_sitter_typescript  # noqa: import check
from symbex_core.indexer import Symbol, extract_symbols_python, extract_symbols_typescript

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
