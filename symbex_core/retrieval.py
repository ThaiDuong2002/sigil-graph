import sqlite3
from dataclasses import dataclass


@dataclass
class SymbolResult:
    symbol_id: int
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    text: str
    is_signature_only: bool
    token_estimate: int
    score: float


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def search_bm25(
    conn: sqlite3.Connection,
    task: str,
    limit: int = 20,
    include_tests: bool = False,
) -> list[SymbolResult]:
    """Full-text search over symbol names and signatures using FTS5 BM25."""
    if not task.strip():
        return []

    try:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.kind, s.file_path,
                   s.start_line, s.end_line, s.source_text,
                   s.signature_text, s.is_test,
                   bm25(bm25_index) AS score
            FROM bm25_index
            JOIN symbols s ON s.id = bm25_index.rowid
            WHERE bm25_index MATCH ?
              AND (? OR s.is_test = 0)
            ORDER BY score
            LIMIT ?
            """,
            (task.strip(), int(include_tests), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 query syntax error — fall back to LIKE
        rows = conn.execute(
            """
            SELECT id, name, kind, file_path, start_line, end_line,
                   source_text, signature_text, is_test, 0.0
            FROM symbols
            WHERE (name LIKE ? OR signature_text LIKE ?)
              AND (? OR is_test = 0)
            LIMIT ?
            """,
            (f"%{task}%", f"%{task}%", int(include_tests), limit),
        ).fetchall()

    results = []
    for row in rows:
        sid, name, kind, file_path, sl, el, source, sig, is_test, score = row
        results.append(SymbolResult(
            symbol_id=sid,
            name=name,
            kind=kind,
            file_path=file_path,
            start_line=sl,
            end_line=el,
            text=source,
            is_signature_only=False,
            token_estimate=_estimate_tokens(source),
            score=float(score),
        ))
    return results


def locate(
    conn: sqlite3.Connection,
    task: str,
    budget: int = 2000,
    cache=None,
) -> list[SymbolResult]:
    """Find the minimal set of symbols relevant to `task` within `budget` tokens."""
    from symbex_core.db import get_index_version
    from symbex_core.graph import get_callees
    from symbex_core.trimmer import trim_to_budget

    version = get_index_version(conn)
    cache_key = (task, version)

    if cache is not None:
        cache.invalidate_if_stale(conn)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    candidates = search_bm25(conn, task, limit=5)

    # Expand: add direct callees in signature-only mode
    callee_names = {sym.name for sym in candidates}
    expanded: list[SymbolResult] = list(candidates)
    for sym in candidates:
        for callee in get_callees(conn, sym.name, depth=1):
            if callee.name not in callee_names:
                callee_names.add(callee.name)
                expanded.append(callee)

    result = trim_to_budget(expanded, budget)

    if cache is not None:
        cache.set(cache_key, result)

    return result
