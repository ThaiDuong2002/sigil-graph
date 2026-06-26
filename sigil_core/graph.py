import json
import sqlite3
from sigil_core.retrieval import SymbolResult, _estimate_tokens


def _row_to_result(row, is_signature_only: bool, call_count: int = 0, call_sites=None) -> SymbolResult:
    sid, name, kind, file_path, sl, el, source, sig = row
    text = sig if is_signature_only else source
    return SymbolResult(
        symbol_id=sid,
        name=name,
        kind=kind,
        file_path=file_path,
        start_line=sl,
        end_line=el,
        text=text,
        is_signature_only=is_signature_only,
        token_estimate=_estimate_tokens(text),
        score=0.0,
        call_count=call_count,
        call_sites=call_sites if call_sites is not None else [],
    )


def get_callers(
    conn: sqlite3.Connection,
    symbol_name: str,
    depth: int = 1,
) -> list[SymbolResult]:
    """Return symbols that call `symbol_name`, sorted by call_count descending."""
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               s.source_text, s.signature_text, e.call_count, e.call_sites
        FROM edges e
        JOIN symbols callee  ON callee.id  = e.callee_id  AND callee.name = ?
        JOIN symbols s       ON s.id       = e.caller_id
        ORDER BY e.call_count DESC
        """,
        (symbol_name,),
    ).fetchall()
    sig_only = depth >= 1
    results = []
    for row in rows:
        sym_row = row[:8]
        call_count = row[8]
        call_sites = json.loads(row[9]) if row[9] else []
        results.append(_row_to_result(sym_row, sig_only, call_count, call_sites))
    return results


def get_callees(
    conn: sqlite3.Connection,
    symbol_name: str,
    depth: int = 1,
) -> list[SymbolResult]:
    """Return symbols called by `symbol_name`, sorted by call_count descending."""
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               s.source_text, s.signature_text, e.call_count, e.call_sites
        FROM edges e
        JOIN symbols caller ON caller.id = e.caller_id AND caller.name = ?
        JOIN symbols s      ON s.id      = e.callee_id
        ORDER BY e.call_count DESC
        """,
        (symbol_name,),
    ).fetchall()
    sig_only = depth >= 1
    results = []
    for row in rows:
        sym_row = row[:8]
        call_count = row[8]
        call_sites = json.loads(row[9]) if row[9] else []
        results.append(_row_to_result(sym_row, sig_only, call_count, call_sites))
    return results


def get_impact(conn: sqlite3.Connection, symbol_name: str) -> dict:
    """How many symbols call `symbol_name`, and where?"""
    callers = get_callers(conn, symbol_name, depth=1)
    return {
        "symbol": symbol_name,
        "count": len(callers),
        "callers": [
            {
                "name": c.name,
                "file_path": c.file_path,
                "start_line": c.start_line,
                "call_count": c.call_count,
                "call_sites": c.call_sites,
            }
            for c in callers
        ],
    }
