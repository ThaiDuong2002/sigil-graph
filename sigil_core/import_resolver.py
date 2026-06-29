import ast
import re
from pathlib import Path
from typing import Callable

from sigil_core.indexer import Symbol

# (caller_name, callee_name, call_count, call_sites)
EdgeData = tuple[str, str, int, list[int]]

# Symbols whose source_text exceeds this are skipped in edge scanning.
# Very large functions (>50KB) are almost always generated/minified code;
# scanning them for every callee candidate would take minutes per file.
_MAX_CALLER_CHARS = 50_000

# Compiled regex cache — callee patterns repeat across many callers/files.
_PATTERN_CACHE: dict[str, re.Pattern] = {}


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
                    alias = alias.strip()
                    if alias:  # guard: malformed "foo as " produces empty alias
                        result[alias] = module
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
    return _find_call_sites_lines(source_text.splitlines(), callee_name, caller_start_line)


def _find_call_sites_lines(lines: list[str], callee_name: str, caller_start_line: int) -> list[int]:
    """Same as _find_call_sites but accepts pre-split lines to avoid repeated splitlines().

    Matches direct calls (foo(...)) and self/this-qualified calls (self.foo(...),
    this.foo(...)), but NOT arbitrary member-access calls (obj.foo(...)) which
    would create false edges to same-file symbols when an external object happens
    to have a method with the same name.
    """
    if not callee_name:
        return []
    if callee_name not in _PATTERN_CACHE:
        # Two alternatives:
        #   1. self.name( or this.name(  — explicit same-instance calls
        #   2. name( when NOT preceded by '.' or a word character — standalone calls
        _PATTERN_CACHE[callee_name] = re.compile(
            r'(?:(?:self|this)\.' + re.escape(callee_name)
            + r'|(?<![.\w])' + re.escape(callee_name)
            + r')\s*\('
        )
    pattern = _PATTERN_CACHE[callee_name]
    return [caller_start_line + i for i, line in enumerate(lines) if pattern.search(line)]


def _find_csharp_call_sites_lines(
    lines: list[str],
    class_name: str,
    method_name: str,
    caller_start_line: int,
) -> list[int]:
    """Find ClassName.MethodName( call sites in C# source lines.

    Matches both regular calls (AuthService.Login()) and generic calls
    (AuthService.Login<T>()).  Requires the exact class name as a prefix so
    arbitrary obj.Method() calls on local variables do NOT create edges.
    """
    if not class_name or not method_name:
        return []
    # Use a namespace-safe cache key — \x00 cannot appear in a C# identifier
    cache_key = f"{class_name}\x00{method_name}"
    if cache_key not in _PATTERN_CACHE:
        _PATTERN_CACHE[cache_key] = re.compile(
            r'(?<![.\w])' + re.escape(class_name)
            + r'\.' + re.escape(method_name)
            + r'\s*[<(]'
        )
    pattern = _PATTERN_CACHE[cache_key]
    return [caller_start_line + i for i, line in enumerate(lines) if pattern.search(line)]


def resolve_edges(
    symbols_by_file: dict[str, list[Symbol]],
    root: Path,
    files_to_resolve: set[str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[EdgeData], list[tuple[str, str]]]:
    """Return (edges, file_imports) for the given symbol graph.

    edges: [(caller_name, callee_name, call_count, call_sites)]
    file_imports: [(importer_rel_path, imported_rel_path)] — all import relationships
        found in the resolved files (used to maintain the file_imports DB table).

    files_to_resolve: if given, only resolve edges for files in this set.
        Edges for other files are left unchanged in the DB.
    progress: optional callable(done_count, total_count, current_file_path)
        called after processing each file.
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
    file_imports: list[tuple[str, str]] = []

    all_files = list(symbols_by_file.items())
    # n_to_resolve: how many files will actually be processed (for progress reporting)
    if files_to_resolve is None:
        n_to_resolve = len(all_files)
    else:
        n_to_resolve = sum(1 for fp, _ in all_files if fp in files_to_resolve)

    resolved_count = 0

    # ── C# cross-file candidate map ──────────────────────────────────────────
    # Maps (class_name, method_name) → (file_path, qualified_sym_name).
    # Built once from the full symbol graph; used inside the per-file loop.
    # Ambiguous entries — same ClassName.MethodName in multiple files — are
    # set to None and excluded from edge creation to keep false positives low.
    _cs_map: dict[tuple[str, str], tuple[str, str] | None] = {}
    for _fp, _syms in symbols_by_file.items():
        if not _fp.endswith(('.cs', '.cshtml')):
            continue
        for _sym in _syms:
            if _sym.kind not in ('method', 'function', 'constructor'):
                continue
            _parts = _sym.name.rsplit('.', 1)
            if len(_parts) != 2:
                continue
            _cls = _parts[0].rsplit('.', 1)[-1]  # direct class name (outermost prefix stripped)
            _key = (_cls, _parts[1])
            if _key in _cs_map:
                existing = _cs_map[_key]
                if existing is not None and existing[0] != _fp:
                    _cs_map[_key] = None  # ambiguous — drop
            else:
                _cs_map[_key] = (_fp, _sym.name)
    # Flatten to a list for fast iteration in the inner loop
    _cs_candidates: list[tuple[str, str, str, str]] = [
        (cls, meth, fp, qual)
        for (cls, meth), v in _cs_map.items()
        if v is not None
        for fp, qual in [v]
    ]

    for file_path, syms in all_files:
        # Incremental mode: skip files not in the re-resolve set
        if files_to_resolve is not None and file_path not in files_to_resolve:
            continue

        abs_path = root / file_path
        try:
            source = abs_path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            resolved_count += 1
            if progress:
                progress(resolved_count, n_to_resolve, file_path)
            continue

        source_lines = source.splitlines()

        # Fill source_text for symbols that have none — avoids loading it from the DB.
        for sym in syms:
            if not sym.source_text:
                sym.source_text = '\n'.join(
                    source_lines[sym.start_line - 1 : sym.end_line]
                )

        if file_path.endswith('.py'):
            imports = extract_python_imports(source)
        elif file_path.endswith(('.cs', '.cshtml')):
            imports = {}
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

        # Record file-level import relationships (deduplicated)
        for rel_target in set(resolved.values()):
            file_imports.append((file_path, rel_target))

        # local_name -> qualified_name for same-file symbols
        same_file: dict[str, str] = {}
        for sym in syms:
            local = sym.name.split('.')[-1]
            same_file[local] = sym.name

        is_csharp = file_path.endswith(('.cs', '.cshtml'))
        cs_callee_files: set[str] = set()  # accumulates cross-file C# imports per file

        for caller_sym in syms:
            # Class source_text includes ALL method bodies — scanning it as a
            # caller is redundant and O(class_size) more expensive.
            if caller_sym.kind == 'class':
                continue

            caller_text = caller_sym.source_text
            # Skip pathologically large symbols (generated/minified code).
            # Scanning a 50KB function body for 100 callee names would take minutes.
            if len(caller_text) > _MAX_CALLER_CHARS:
                continue

            caller_local = caller_sym.name.split('.')[-1]
            caller_lines = None  # lazy — only split if a pre-filter passes

            # Cross-file edges
            for local_name, rel_target_file in resolved.items():
                if not local_name:  # guard: malformed import produced empty name
                    continue
                if local_name not in caller_text:
                    continue
                if caller_lines is None:
                    caller_lines = caller_text.splitlines()
                sites = _find_call_sites_lines(
                    caller_lines, local_name, caller_sym.start_line
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
                if not local_name:  # guard: empty symbol name (shouldn't happen)
                    continue
                if local_name == caller_local:
                    continue
                if local_name in resolved:
                    continue
                if local_name not in caller_text:
                    continue
                if caller_lines is None:
                    caller_lines = caller_text.splitlines()
                sites = _find_call_sites_lines(
                    caller_lines, local_name, caller_sym.start_line
                )
                if sites:
                    edges.append((
                        caller_sym.name,
                        qualified_name,
                        len(sites),
                        sites,
                    ))

            # C# cross-file edges: ClassName.MethodName( pattern detection.
            # Skips non-C# files and files with no unambiguous cross-file candidates.
            if is_csharp and _cs_candidates:
                for cls_name, method_name, callee_fp, callee_qual in _cs_candidates:
                    if callee_fp == file_path:
                        continue  # same-file already handled above
                    # Quick double text-filter before compiling/running the regex
                    if cls_name not in caller_text or method_name not in caller_text:
                        continue
                    if caller_lines is None:
                        caller_lines = caller_text.splitlines()
                    sites = _find_csharp_call_sites_lines(
                        caller_lines, cls_name, method_name, caller_sym.start_line
                    )
                    if sites:
                        edges.append((caller_sym.name, callee_qual, len(sites), sites))
                        cs_callee_files.add(callee_fp)

        # Flush C# file-level import relationships (deduplicated per file)
        for callee_fp in cs_callee_files:
            file_imports.append((file_path, callee_fp))

        resolved_count += 1
        if progress:
            progress(resolved_count, n_to_resolve, file_path)

    return edges, file_imports
