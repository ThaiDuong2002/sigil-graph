import ast
import re
from pathlib import Path

from symbex_core.indexer import Symbol


def extract_python_imports(source: str) -> dict[str, str]:
    """Returns {local_name: module_dotted_path} for all from-imports."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == '*':
                    continue
                local = alias.asname if alias.asname else alias.name
                result[local] = node.module
    return result


_TS_IMPORT_RE = re.compile(
    r"""import\s+(?:
        (?P<default>\w+)\s*,?\s*)?
        (?:\{(?P<named>[^}]+)\})?
    \s+from\s+['"](?P<module>[^'"]+)['"]""",
    re.VERBOSE,
)


def extract_typescript_imports(source: str) -> dict[str, str]:
    """Returns {local_name: module_path} for TS/JS import statements."""
    result: dict[str, str] = {}
    for m in _TS_IMPORT_RE.finditer(source):
        module = m.group('module')
        if m.group('default'):
            result[m.group('default').strip()] = module
        if m.group('named'):
            for part in m.group('named').split(','):
                part = part.strip()
                if not part:
                    continue
                if ' as ' in part:
                    _, alias = part.split(' as ', 1)
                    result[alias.strip()] = module
                else:
                    result[part] = module
    return result


def _module_to_file(module: str, root: Path, current_file: Path) -> Path | None:
    """Best-effort: map a module path to a .py file under root."""
    if module.startswith('.'):
        # relative import
        base = current_file.parent
        parts = module.lstrip('.')
        if parts:
            candidate = base / Path(parts.replace('.', '/'))
        else:
            candidate = base
        for suffix in ('.py', '/__init__.py'):
            p = Path(str(candidate) + suffix)
            if p.exists():
                return p
        return None
    # absolute import: try root/module/path.py
    candidate = root / Path(module.replace('.', '/'))
    for suffix in ('.py', '/__init__.py'):
        p = Path(str(candidate) + suffix)
        if p.exists():
            return p
    return None


def resolve_edges(
    symbols_by_file: dict[str, list[Symbol]],
    root: Path,
) -> list[tuple[str, str]]:
    """
    Returns [(caller_qualified_name, callee_qualified_name)] pairs.
    Uses import maps to resolve cross-file calls.
    """
    # Build lookup: (file_path, local_name) -> qualified symbol name
    name_index: dict[tuple[str, str], str] = {}
    for file_path, syms in symbols_by_file.items():
        for sym in syms:
            local = sym.name.split('.')[-1]  # strip class prefix
            name_index[(file_path, local)] = sym.name

    edges: list[tuple[str, str]] = []

    for file_path, syms in symbols_by_file.items():
        path = Path(file_path)
        try:
            source = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue

        if file_path.endswith('.py'):
            imports = extract_python_imports(source)
        else:
            imports = extract_typescript_imports(source)

        # Map: local_name -> resolved file_path
        resolved: dict[str, str] = {}
        for local_name, module in imports.items():
            target_file = _module_to_file(module, root, path)
            if target_file:
                resolved[local_name] = str(target_file.resolve())

        for caller_sym in syms:
            # Find call sites in caller's source text (simple name matching)
            for local_name, target_file in resolved.items():
                if local_name + '(' in caller_sym.source_text:
                    callee_key = (target_file, local_name)
                    if callee_key in name_index:
                        edges.append((caller_sym.name, name_index[callee_key]))

    return edges
