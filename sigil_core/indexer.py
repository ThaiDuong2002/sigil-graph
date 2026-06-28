import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import hashlib

import re

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser, Node

_PY_LANG = Language(tspython.language())
_PY_PARSER = Parser(_PY_LANG)

_TS_LANG = Language(tstypescript.language_typescript())
_TSX_LANG = Language(tstypescript.language_tsx())
_TS_PARSER = Parser(_TS_LANG)
_TSX_PARSER = Parser(_TSX_LANG)

_CS_LANG = Language(tscsharp.language())
_CS_PARSER = Parser(_CS_LANG)

EXCLUDE_DIRS = frozenset({
    'node_modules', 'venv', '.venv', 'env', '.env',
    'dist', 'build', '__pycache__', '.git', '.sigil',
    'bin', 'obj', 'packages',  # .NET build artefacts
})
EXCLUDE_SIZE = 500 * 1024
TEST_SUFFIXES = (
    '_test.py', '.test.ts', '.test.js', '.spec.ts', '.spec.js',
    'Tests.cs', 'Test.cs', '_tests.cs',  # NUnit / xUnit
)
TEST_DIRS = frozenset({'tests', '__tests__', 'test', 'Tests', 'Test'})


@dataclass
class Symbol:
    name: str
    kind: str          # 'function' | 'class' | 'method' | 'constant'
    file_path: str
    start_line: int
    end_line: int
    source_text: str
    signature_text: str
    is_test: bool = False
    summary: str = ''


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_test_file(path: Path) -> bool:
    if any(path.name.endswith(s) for s in TEST_SUFFIXES):
        return True
    return bool(set(path.parts) & TEST_DIRS)


def extract_symbols_python(source: str, file_path: str, is_test: bool) -> list[Symbol]:
    tree = _PY_PARSER.parse(source.encode())
    lines = source.splitlines()
    symbols: list[Symbol] = []

    def _source(start_row: int, end_row: int) -> str:
        return '\n'.join(lines[start_row : end_row + 1])

    def _sig(start_row: int) -> str:
        raw = lines[start_row] if lines else ''
        # If this line is a decorator, walk forward to find the actual def/class line
        idx = start_row
        while raw.lstrip().startswith('@') and idx + 1 < len(lines):
            idx += 1
            raw = lines[idx]
        raw = raw.rstrip()
        # strip trailing colon if present to add ellipsis
        if raw.endswith(':'):
            raw = raw[:-1]
        # strip trailing open-paren or trailing comma (truncated multi-line sig)
        raw = raw.rstrip('(').rstrip(',').rstrip()
        return raw + ': ...'

    def _walk(node: Node, class_name: str | None = None) -> None:
        if node.type == 'function_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                raw = name_node.text.decode()
                qualified = f"{class_name}.{raw}" if class_name else raw
                symbols.append(Symbol(
                    name=qualified,
                    kind='method' if class_name else 'function',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
            for child in node.children:
                _walk(child, class_name)

        elif node.type == 'class_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                cname = name_node.text.decode()
                symbols.append(Symbol(
                    name=cname,
                    kind='class',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
                # Only recurse into block children to avoid double-inserting methods
                for child in node.children:
                    if child.type == 'block':
                        _walk(child, cname)
        else:
            for child in node.children:
                _walk(child, class_name)

    _walk(tree.root_node)
    return symbols


def extract_symbols_typescript(source: str, file_path: str, is_test: bool) -> list[Symbol]:
    parser = _TSX_PARSER if file_path.endswith(('.tsx', '.jsx')) else _TS_PARSER
    tree = parser.parse(source.encode())
    lines = source.splitlines()
    symbols: list[Symbol] = []

    def _source(start_row: int, end_row: int) -> str:
        return '\n'.join(lines[start_row : end_row + 1])

    def _sig(start_row: int) -> str:
        raw = lines[start_row].rstrip() if lines else ''
        # If this line is a decorator, walk forward to find the actual def/class line
        idx = start_row
        while raw.lstrip().startswith('@') and idx + 1 < len(lines):
            idx += 1
            raw = lines[idx].rstrip()
        if raw.endswith('{'):
            raw = raw[:-1].rstrip()
        # strip trailing open-paren or trailing comma (truncated multi-line sig)
        raw = raw.rstrip('(').rstrip(',').rstrip()
        return raw + ': ...'

    def _walk(node: Node, class_name: str | None = None) -> None:
        if node.type == 'function_declaration':
            name_node = node.child_by_field_name('name')
            if name_node:
                raw = name_node.text.decode()
                qualified = f"{class_name}.{raw}" if class_name else raw
                symbols.append(Symbol(
                    name=qualified,
                    kind='method' if class_name else 'function',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
            for child in node.children:
                _walk(child, class_name)

        elif node.type == 'method_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                raw = name_node.text.decode()
                qualified = f"{class_name}.{raw}" if class_name else raw
                symbols.append(Symbol(
                    name=qualified,
                    kind='method',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
            # method_definition contains a statement_block; no further method nesting expected
            for child in node.children:
                _walk(child, class_name)

        elif node.type == 'class_declaration':
            name_node = node.child_by_field_name('name')
            if name_node:
                cname = name_node.text.decode()
                symbols.append(Symbol(
                    name=cname,
                    kind='class',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
                # Only recurse into class_body to avoid double-inserting methods
                for child in node.children:
                    if child.type == 'class_body':
                        _walk(child, cname)
        else:
            for child in node.children:
                _walk(child, class_name)

    _walk(tree.root_node)
    return symbols


def _cs_name_before(node: Node, stop_types: set[str]) -> str | None:
    """Return the last bare `identifier` child before any node in stop_types."""
    prev_id: str | None = None
    for child in node.children:
        if child.type in stop_types:
            break
        if child.type == 'identifier':
            prev_id = child.text.decode()
    return prev_id


def extract_symbols_csharp(source: str, file_path: str, is_test: bool) -> list[Symbol]:
    tree = _CS_PARSER.parse(source.encode())
    lines = source.splitlines()
    symbols: list[Symbol] = []

    def _source(start_row: int, end_row: int) -> str:
        return '\n'.join(lines[start_row : end_row + 1])

    def _sig(start_row: int) -> str:
        raw = lines[start_row] if lines else ''
        idx = start_row
        # Skip C# attribute lines like [HttpGet], [Route("...")]
        while raw.lstrip().startswith('[') and idx + 1 < len(lines):
            idx += 1
            raw = lines[idx]
        raw = raw.rstrip()
        if raw.endswith('{'):
            raw = raw[:-1].rstrip() + ' { ... }'
        return raw

    def _walk(node: Node, class_name: str | None = None) -> None:
        t = node.type

        if t in ('class_declaration', 'interface_declaration',
                  'struct_declaration', 'record_declaration',
                  'record_struct_declaration'):
            cname = _cs_name_before(
                node, {'declaration_list', 'base_list', 'type_parameter_list'}
            )
            if cname:
                symbols.append(Symbol(
                    name=cname,
                    kind='class',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))
                body = next(
                    (c for c in node.children if c.type == 'declaration_list'), None
                )
                if body:
                    _walk(body, cname)

        elif t == 'enum_declaration':
            cname = _cs_name_before(node, {'enum_member_declaration_list'})
            if cname:
                symbols.append(Symbol(
                    name=cname,
                    kind='class',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))

        elif t in ('method_declaration', 'local_function_statement'):
            mname = _cs_name_before(
                node, {'parameter_list', 'type_parameter_list', 'block'}
            )
            if mname:
                qualified = f"{class_name}.{mname}" if class_name else mname
                symbols.append(Symbol(
                    name=qualified,
                    kind='method' if class_name else 'function',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))

        elif t == 'constructor_declaration':
            mname = _cs_name_before(node, {'parameter_list'})
            if mname:
                qualified = f"{class_name}.{mname}" if class_name else mname
                symbols.append(Symbol(
                    name=qualified,
                    kind='method',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))

        elif t == 'property_declaration':
            pname = _cs_name_before(
                node, {'accessor_list', 'arrow_expression_clause', 'block'}
            )
            if pname:
                qualified = f"{class_name}.{pname}" if class_name else pname
                symbols.append(Symbol(
                    name=qualified,
                    kind='method',
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=_source(node.start_point[0], node.end_point[0]),
                    signature_text=_sig(node.start_point[0]),
                    is_test=is_test,
                ))

        else:
            for child in node.children:
                _walk(child, class_name)

    _walk(tree.root_node)
    return symbols


_RAZOR_FUNCTIONS_RE = re.compile(r'@functions\s*(\{)', re.IGNORECASE)


def _extract_brace_block(source: str, open_pos: int) -> tuple[str, int]:
    """Extract content between matching braces starting at open_pos."""
    depth = 0
    pos = open_pos
    while pos < len(source):
        if source[pos] == '{':
            depth += 1
        elif source[pos] == '}':
            depth -= 1
            if depth == 0:
                return source[open_pos + 1 : pos], pos
        pos += 1
    return source[open_pos + 1 :], len(source)


def extract_symbols_razor(source: str, file_path: str, is_test: bool) -> list[Symbol]:
    """Extract C# symbols from @functions { ... } blocks in Razor (.cshtml) files."""
    symbols: list[Symbol] = []
    for m in _RAZOR_FUNCTIONS_RE.finditer(source):
        brace_pos = m.start(1)
        line_offset = source[:brace_pos + 1].count('\n')
        inner, _ = _extract_brace_block(source, brace_pos)
        for sym in extract_symbols_csharp(inner, file_path, is_test):
            symbols.append(Symbol(
                name=sym.name,
                kind=sym.kind,
                file_path=sym.file_path,
                start_line=sym.start_line + line_offset,
                end_line=sym.end_line + line_offset,
                source_text=sym.source_text,
                signature_text=sym.signature_text,
                is_test=sym.is_test,
            ))
    return symbols


_SUPPORTED_EXTS = frozenset(('.py', '.ts', '.js', '.tsx', '.jsx', '.cs', '.cshtml'))


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield all source files under root, excluding EXCLUDE_DIRS and large files.

    Uses os.walk with in-place directory pruning so excluded dirs (node_modules,
    venv, .git, etc.) are never descended into — much faster than rglob for large
    projects.
    """
    for dirpath_str, dirnames, filenames in os.walk(str(root)):
        # Prune excluded dirs in-place — os.walk will not descend into them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        dirpath = Path(dirpath_str)
        for fname in filenames:
            if Path(fname).suffix not in _SUPPORTED_EXTS:
                continue
            path = dirpath / fname
            try:
                if path.stat().st_size > EXCLUDE_SIZE:
                    continue
            except OSError:
                continue
            yield path


def _extract_file(path: Path, root: Path) -> list[Symbol]:
    """Extract symbols from a source file."""
    source = path.read_text(encoding='utf-8', errors='ignore')
    rel = str(path.relative_to(root))
    test = is_test_file(path)
    if path.suffix == '.py':
        return extract_symbols_python(source, rel, test)
    if path.suffix == '.cs':
        return extract_symbols_csharp(source, rel, test)
    if path.suffix == '.cshtml':
        return extract_symbols_razor(source, rel, test)
    return extract_symbols_typescript(source, rel, test)


def index_project(
    root: Path,
    conn: sqlite3.Connection,
    progress=None,
    rebuild_edges: bool = False,
) -> dict:
    """Index all source files in root incrementally. Returns stats dict.

    progress: optional callable(str) for user-facing status lines (e.g. click.echo).
    rebuild_edges: force Phase 6 (edge resolution) even when no files changed.
    """
    from sigil_core.db import bump_index_version
    from sigil_core.import_resolver import resolve_edges

    def _p(msg: str) -> None:
        if progress:
            progress(msg)

    # Load entire files table once — avoids one DB query per file during scan
    file_cache: dict[str, tuple[str, float]] = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT path, hash, mtime FROM files").fetchall()
    }

    # Snapshot symbol names for diff (names only — fast even at 100k symbols)
    old_names: set[str] = {
        row[0] for row in conn.execute("SELECT name FROM symbols").fetchall()
    }

    # ── Phase 1: scan — mtime early-exit (no file read for unchanged files) ──
    on_disk_rels: set[str] = set()
    needs_hash: list[tuple[Path, str, float]] = []   # mtime changed, need hash check

    for path in iter_source_files(root):
        rel = str(path.relative_to(root))
        on_disk_rels.add(rel)
        mtime = path.stat().st_mtime
        cached = file_cache.get(rel)
        if cached and cached[1] == mtime:
            continue  # mtime unchanged → content definitely same, skip
        needs_hash.append((path, rel, mtime))

    # ── Phase 2: compute hashes in parallel (I/O-bound, thread-safe) ─────────
    def _do_hash(args: tuple[Path, str, float]) -> tuple[Path, str, float, str]:
        path, rel, mtime = args
        return path, rel, mtime, file_hash(path)

    if needs_hash:
        workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            hashed: list[tuple[Path, str, float, str]] = list(
                pool.map(_do_hash, needs_hash)
            )
    else:
        hashed = []

    # ── Phase 3: split mtime-only vs. content-changed ────────────────────────
    to_parse: list[tuple[Path, str, float, str]] = []
    mtime_only: list[tuple[float, str]] = []

    for path, rel, mtime, h in hashed:
        cached = file_cache.get(rel)
        if cached and cached[0] == h:
            mtime_only.append((mtime, rel))   # content same, just bump mtime record
        else:
            to_parse.append((path, rel, mtime, h))

    if mtime_only:
        conn.executemany("UPDATE files SET mtime=? WHERE path=?", mtime_only)
        conn.commit()

    # ── Phase 4: parse content-changed files (sequential — tree-sitter not thread-safe) ──
    changed_files: list[Path] = []
    total_new_symbols = 0
    new_file_sym_names: set[str] = set()   # names emitted from re-parsed files

    if to_parse:
        _p(f"Parsing {len(to_parse)} changed file(s)...")

    for path, rel, mtime, h in to_parse:
        symbols = _extract_file(path, root)

        old_ids = [r[0] for r in conn.execute(
            "SELECT id FROM symbols WHERE file_path=?", (rel,)
        ).fetchall()]
        if old_ids:
            ph = ','.join('?' * len(old_ids))
            conn.execute(
                f"DELETE FROM edges WHERE caller_id IN ({ph}) OR callee_id IN ({ph})",
                old_ids + old_ids,
            )
            conn.execute(f"DELETE FROM symbols WHERE id IN ({ph})", old_ids)

        for sym in symbols:
            conn.execute(
                "INSERT INTO symbols(name,kind,file_path,start_line,end_line,"
                "source_text,signature_text,is_test) VALUES(?,?,?,?,?,?,?,?)",
                (sym.name, sym.kind, sym.file_path, sym.start_line, sym.end_line,
                 sym.source_text, sym.signature_text, int(sym.is_test)),
            )
            new_file_sym_names.add(sym.name)

        conn.execute(
            "INSERT OR REPLACE INTO files(path,mtime,hash) VALUES(?,?,?)",
            (rel, mtime, h),
        )
        conn.commit()
        changed_files.append(path)
        total_new_symbols += len(symbols)

    # ── Phase 5: remove ghost files (deleted/renamed) ─────────────────────────
    ghost_rels = set(file_cache.keys()) - on_disk_rels
    if ghost_rels:
        for ghost_rel in ghost_rels:
            old_ids = [r[0] for r in conn.execute(
                "SELECT id FROM symbols WHERE file_path=?", (ghost_rel,)
            ).fetchall()]
            if old_ids:
                ph = ','.join('?' * len(old_ids))
                conn.execute(
                    f"DELETE FROM edges WHERE caller_id IN ({ph}) OR callee_id IN ({ph})",
                    old_ids + old_ids,
                )
                conn.execute(f"DELETE FROM symbols WHERE id IN ({ph})", old_ids)
            conn.execute("DELETE FROM files WHERE path=?", (ghost_rel,))
        conn.commit()

    # ── Phase 6: rebuild edges + FTS if anything changed ─────────────────────
    if changed_files or ghost_rels or rebuild_edges:
        # Load symbols WITHOUT source_text — resolve_edges reads files itself,
        # so loading source_text here would be double I/O for large projects.
        full_symbols: dict[str, list[Symbol]] = {}
        for row in conn.execute(
            "SELECT name,kind,file_path,start_line,end_line,signature_text,is_test "
            "FROM symbols"
        ).fetchall():
            sym = Symbol(
                name=row[0], kind=row[1], file_path=row[2],
                start_line=row[3], end_line=row[4],
                source_text='',  # filled in by resolve_edges from file content
                signature_text=row[5],
                is_test=bool(row[6]),
            )
            full_symbols.setdefault(row[2], []).append(sym)

        n_files = len(full_symbols)
        _p(f"Resolving call graph for {n_files} file(s)...")
        conn.execute("DELETE FROM edges")
        edges = resolve_edges(full_symbols, root)
        _p(f"Found {len(edges)} edges.")

        # One query to build name→id map; avoids 2 SQL queries per edge.
        name_to_id: dict[str, int] = {
            row[0]: row[1]
            for row in conn.execute("SELECT name, id FROM symbols")
        }
        edge_rows = [
            (name_to_id[cn], name_to_id[ce], call_count, json.dumps(call_sites))
            for cn, ce, call_count, call_sites in edges
            if cn in name_to_id and ce in name_to_id
        ]
        if edge_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO edges(caller_id, callee_id, call_count, call_sites) "
                "VALUES(?,?,?,?)",
                edge_rows,
            )

        conn.execute("INSERT INTO bm25_index(bm25_index) VALUES('rebuild')")
        conn.commit()
        bump_index_version(conn)

    # ── Diff: what was added / removed / changed ──────────────────────────────
    new_names: set[str] = {
        row[0] for row in conn.execute("SELECT name FROM symbols").fetchall()
    }
    added   = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    # "changed" = re-parsed symbols that existed before (hash changed → content changed)
    changed_sym_names = sorted(new_file_sym_names & old_names & new_names)

    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return {
        "symbols":       total_new_symbols,
        "files":         total_files,
        "edges":         total_edges,
        "added":         added,
        "removed":       removed,
        "changed":       changed_sym_names,
        "files_changed": len(changed_files),
    }
