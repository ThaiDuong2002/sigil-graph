from pathlib import Path
from sigil_core.db import get_db, init_schema
from sigil_core.indexer import index_project
from sigil_core.knowledge import (
    generate_knowledge,
    write_knowledge,
    _extract_docstring,
    _classify_name,
    _has_type_hints,
    _detect_layer,
)


def _setup(tmp_path: Path):
    (tmp_path / "tokens.py").write_text(
        'def validate_token(token: str) -> bool:\n'
        '    """Check if a token is valid."""\n'
        '    return len(token) == 32\n'
    )
    (tmp_path / "auth.py").write_text(
        'from tokens import validate_token\n\n'
        'class AuthService:\n'
        '    """Handles user authentication."""\n'
        '    def login(self, user_id: int, token: str) -> bool:\n'
        '        return validate_token(token)\n'
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    return conn


# --- Unit tests for helpers ---

def test_extract_docstring_triple_double():
    src = 'def foo():\n    """Return the answer."""\n    return 42\n'
    assert _extract_docstring(src) == "Return the answer."


def test_extract_docstring_triple_single():
    src = "def bar():\n    '''Do something.'''\n    pass\n"
    assert _extract_docstring(src) == "Do something."


def test_extract_docstring_absent():
    assert _extract_docstring("def foo():\n    return 1\n") == ""


def test_classify_name_snake():
    assert _classify_name("validate_token") == "snake_case"


def test_classify_name_pascal():
    assert _classify_name("AuthService") == "PascalCase"


def test_classify_name_camel():
    assert _classify_name("getUserById") == "camelCase"


def test_has_type_hints_with_return():
    assert _has_type_hints("def foo(x: int) -> bool: ...") is True


def test_has_type_hints_without():
    assert _has_type_hints("def foo(x): ...") is False


def test_detect_layer_service():
    assert _detect_layer("services/auth_service.py") == "Service"


def test_detect_layer_model():
    assert _detect_layer("models/user.py") == "Model"


def test_detect_layer_entry():
    assert _detect_layer("main.py") == "Entry"


# --- Integration tests ---

def test_generate_knowledge_contains_sections(tmp_path):
    conn = _setup(tmp_path)
    md = generate_knowledge(conn, tmp_path)
    assert "## Architecture" in md
    assert "## Business Logic" in md
    assert "## Code Conventions" in md
    assert "## Hotspots" in md


def test_generate_knowledge_contains_class_name(tmp_path):
    conn = _setup(tmp_path)
    md = generate_knowledge(conn, tmp_path)
    assert "AuthService" in md


def test_generate_knowledge_naming_convention(tmp_path):
    conn = _setup(tmp_path)
    md = generate_knowledge(conn, tmp_path)
    assert "snake_case" in md


def test_generate_knowledge_type_hints(tmp_path):
    conn = _setup(tmp_path)
    md = generate_knowledge(conn, tmp_path)
    assert "%" in md  # type hint coverage percentage


def test_write_knowledge_creates_file(tmp_path):
    conn = _setup(tmp_path)
    out = write_knowledge(conn, tmp_path)
    assert out.exists()
    assert out.name == "knowledge.md"
    content = out.read_text()
    assert "Project Knowledge" in content


def test_generate_knowledge_entry_points(tmp_path):
    conn = _setup(tmp_path)
    md = generate_knowledge(conn, tmp_path)
    assert "Entry points" in md
