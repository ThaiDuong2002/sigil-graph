from dataclasses import dataclass
from pathlib import Path
import hashlib

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

_PY_LANG = Language(tspython.language())
_PY_PARSER = Parser(_PY_LANG)

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
