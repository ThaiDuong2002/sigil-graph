from pathlib import Path
from sigil_core.import_resolver import extract_python_imports, extract_typescript_imports

CALLER = Path(__file__).parent / "fixtures" / "caller.py"

def test_python_extracts_from_import():
    source = CALLER.read_text()
    imports = extract_python_imports(source)
    assert imports["validate_token"] == "fixtures.callee"
    assert imports["refresh_token"] == "fixtures.callee"

def test_python_handles_aliased_import():
    source = "import os.path as osp\nfrom pathlib import Path as P\n"
    imports = extract_python_imports(source)
    assert imports["P"] == "pathlib"

def test_python_skips_star_imports():
    source = "from utils import *\n"
    imports = extract_python_imports(source)
    assert imports == {}

def test_typescript_extracts_named_import():
    source = "import { validate, refresh } from './tokens';\n"
    imports = extract_typescript_imports(source)
    assert imports["validate"] == "./tokens"
    assert imports["refresh"] == "./tokens"

def test_typescript_extracts_default_import():
    source = "import AuthService from '../auth';\n"
    imports = extract_typescript_imports(source)
    assert imports["AuthService"] == "../auth"
