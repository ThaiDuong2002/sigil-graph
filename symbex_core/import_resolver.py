import ast
import re
from pathlib import Path

from symbex_core.indexer import Symbol

# (caller_name, callee_name, call_count, call_sites)
EdgeData = tuple[str, str, int, list[int]]


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
    """Best-effort: map a module/import path to a source file under root."""
    _py_suffixes = ('.py', '/__init__.py')
    _ts_suffixes = ('.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js')

    if module.startswith('.'):
        # relative import
        base = current_file.parent
        parts = module.lstrip('.')
        if parts:
            candidate = base / Path(parts.replace('.', '/'))
        else:
            candidate = base
        for suffix in _py_suffixes + _ts_suffixes:
            p = Path(str(candidate) + suffix)
            if p.exists():
                return p
        return None
    # absolute import: try root/module/path.py (Python) or root/module (TS)
    candidate = root / Path(module.replace('.', '/'))
    for suffix in _py_suffixes + _ts_suffixes:
        p = Path(str(candidate) + suffix)
        if p.exists():
            return p
    return None


def _find_call_sites(source_text: str, callee_name: str, caller_start_line: int) -> list[int]:
    """Return 1-based absolute line numbers where callee_name( appears in source_text."""
    pattern = re.compile(r'\b' + re.escape(callee_name) + r'\s*\(')
    sites = []
    for i, line in enumerate(source_text.splitlines()):
        if pattern.search(line):
            sites.append(caller_start_line + i)
    return sites


def resolve_edges(
    symbols_by_file: dict[str, list[Symbol]],
    root: Path,
) -> list[EdgeData]:
    """
    Returns [(caller_name, callee_name, call_count, call_sites)] for all detected calls.

    Covers both cross-file calls (via import resolution) and same-file calls.
    call_sites contains 1-based absolute line numbers in the caller's source file.
    """
    # Build global lookup: (file_path, local_name) -> qualified_name
    name_index: dict[tuple[str, str], str] = {}
    for file_path, syms in symbols_by_file.items():
        for sym in syms:
            local = sym.name.split('.')[-1]
            name_index[(file_path, local)] = sym.name

    abs_to_rel: dict[str, str] = {}
    for file_path in symbols_by_file:
        abs_to_rel[str((root / file_path).resolve())] = file_path

    edges: list[EdgeData] = []

    for file_path, syms in symbols_by_file.items():
        abs_path = root / file_path
        try:
            source = abs_path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue

        if file_path.endswith('.py'):
            imports = extract_python_imports(source)
        else:
            imports = extract_typescript_imports(source)

        # local_name -> relative file_path for cross-file imports
        resolved: dict[str, str] = {}
        for local_name, module in imports.items():
            target_file = _module_to_file(module, root, abs_path)
            if target_file:
                abs_target = str(target_file.resolve())
                rel_target = abs_to_rel.get(abs_target)
                if rel_target:
                    resolved[local_name] = rel_target

        # local_name -> qualified_name for same-file symbols
        same_file: dict[str, str] = {}
        for sym in syms:
            local = sym.name.split('.')[-1]
            same_file[local] = sym.name

        for caller_sym in syms:
            caller_local = caller_sym.name.split('.')[-1]

            # Cross-file edges
            for local_name, rel_target_file in resolved.items():
                sites = _find_call_sites(
                    caller_sym.source_text, local_name, caller_sym.start_line
                )
                if sites:
                    callee_key = (rel_target_file, local_name)
                    if callee_key in name_index:
                        edges.append((
                            caller_sym.name,
                            name_index[callee_key],
                            len(sites),
                            sites,
                        ))

            # Same-file edges (skip symbols already covered by imports, skip self)
            for local_name, qualified_name in same_file.items():
                if local_name == caller_local:
                    continue
                if local_name in resolved:
                    continue
                sites = _find_call_sites(
                    caller_sym.source_text, local_name, caller_sym.start_line
                )
                if sites:
                    edges.append((
                        caller_sym.name,
                        qualified_name,
                        len(sites),
                        sites,
                    ))

    return edges
