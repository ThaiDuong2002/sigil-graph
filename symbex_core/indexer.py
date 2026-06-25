import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import hashlib

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser, Node

_PY_LANG = Language(tspython.language())
_PY_PARSER = Parser(_PY_LANG)

_TS_LANG = Language(tstypescript.language_typescript())
_TSX_LANG = Language(tstypescript.language_tsx())
_TS_PARSER = Parser(_TS_LANG)
_TSX_PARSER = Parser(_TSX_LANG)

EXCLUDE_DIRS = frozenset({
    'node_modules', 'venv', '.venv', 'env', '.env',
    'dist', 'build', '__pycache__', '.git', '.symbex',
})
EXCLUDE_SIZE = 500 * 1024
TEST_SUFFIXES = ('_test.py', '.test.ts', '.test.js', '.spec.ts', '.spec.js')
TEST_DIRS = frozenset({'tests', '__tests__', 'test'})


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
        # strip trailing colon if present to add ellipsis
        raw = raw.rstrip()
        if raw.endswith(':'):
            raw = raw[:-1]
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
                for child in node.children:
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
        if raw.endswith('{'):
            raw = raw[:-1].rstrip()
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
                for child in node.children:
                    _walk(child, cname)
        else:
            for child in node.children:
                _walk(child, class_name)

    _walk(tree.root_node)
    return symbols


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield all source files under root, excluding EXCLUDE_DIRS and large files."""
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        if any(excl in path.parts for excl in EXCLUDE_DIRS):
            continue
        if path.stat().st_size > EXCLUDE_SIZE:
            continue
        if path.suffix in ('.py', '.ts', '.js', '.tsx', '.jsx'):
            yield path


def _extract_file(path: Path, root: Path) -> list[Symbol]:
    """Extract symbols from a source file."""
    source = path.read_text(encoding='utf-8', errors='ignore')
    rel = str(path.relative_to(root))
    test = is_test_file(path)
    if path.suffix == '.py':
        return extract_symbols_python(source, rel, test)
    return extract_symbols_typescript(source, rel, test)


def _upsert_file(path: Path, root: Path, conn: sqlite3.Connection) -> list[Symbol] | None:
    """Re-index a file if its hash changed. Returns new symbols or None if unchanged."""
    rel = str(path.relative_to(root))
    current_hash = file_hash(path)
    row = conn.execute("SELECT hash FROM files WHERE path=?", (rel,)).fetchone()
    if row and row[0] == current_hash:
        return None  # unchanged

    symbols = _extract_file(path, root)

    # Remove old data for this file
    old_ids = [r[0] for r in conn.execute(
        "SELECT id FROM symbols WHERE file_path=?", (rel,)
    ).fetchall()]
    if old_ids:
        placeholders = ','.join('?' * len(old_ids))
        conn.execute(
            f"DELETE FROM edges WHERE caller_id IN ({placeholders}) OR callee_id IN ({placeholders})",
            old_ids + old_ids,
        )
        conn.execute(f"DELETE FROM symbols WHERE id IN ({placeholders})", old_ids)

    for sym in symbols:
        conn.execute(
            "INSERT INTO symbols(name,kind,file_path,start_line,end_line,"
            "source_text,signature_text,is_test) VALUES(?,?,?,?,?,?,?,?)",
            (sym.name, sym.kind, sym.file_path, sym.start_line, sym.end_line,
             sym.source_text, sym.signature_text, int(sym.is_test)),
        )

    mtime = path.stat().st_mtime
    conn.execute(
        "INSERT OR REPLACE INTO files(path,mtime,hash) VALUES(?,?,?)",
        (rel, mtime, current_hash),
    )
    return symbols


def index_project(root: Path, conn: sqlite3.Connection) -> dict:
    """Index all source files in root incrementally. Returns stats dict."""
    from symbex_core.db import bump_index_version
    from symbex_core.import_resolver import resolve_edges

    all_symbols: dict[str, list[Symbol]] = {}
    changed_files: list[Path] = []
    total_symbols = 0

    for path in iter_source_files(root):
        result = _upsert_file(path, root, conn)
        if result is not None:
            rel = str(path.relative_to(root))
            all_symbols[rel] = result
            changed_files.append(path)
            total_symbols += len(result)

    if changed_files:
        # Rebuild edges for changed files
        edges = resolve_edges(all_symbols, root)
        for caller_name, callee_name in edges:
            caller_row = conn.execute(
                "SELECT id FROM symbols WHERE name=?", (caller_name,)
            ).fetchone()
            callee_row = conn.execute(
                "SELECT id FROM symbols WHERE name=?", (callee_name,)
            ).fetchone()
            if caller_row and callee_row:
                conn.execute(
                    "INSERT OR IGNORE INTO edges(caller_id, callee_id) VALUES(?,?)",
                    (caller_row[0], callee_row[0]),
                )

        # Rebuild FTS5 index
        conn.execute("INSERT INTO bm25_index(bm25_index) VALUES('rebuild')")
        conn.commit()
        bump_index_version(conn)

    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return {"symbols": total_symbols, "files": total_files, "edges": total_edges}
