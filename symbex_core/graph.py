import sqlite3
from symbex_core.retrieval import SymbolResult, _estimate_tokens


def _row_to_result(row, is_signature_only: bool) -> SymbolResult:
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
    )


def get_callers(
    conn: sqlite3.Connection,
    symbol_name: str,
    depth: int = 1,
) -> list[SymbolResult]:
    """Return symbols that call `symbol_name`, up to `depth` levels."""
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               s.source_text, s.signature_text
        FROM edges e
        JOIN symbols callee  ON callee.id  = e.callee_id  AND callee.name = ?
        JOIN symbols s       ON s.id       = e.caller_id
        """,
        (symbol_name,),
    ).fetchall()
    sig_only = depth >= 1
    return [_row_to_result(row, sig_only) for row in rows]


def get_callees(
    conn: sqlite3.Connection,
    symbol_name: str,
    depth: int = 1,
) -> list[SymbolResult]:
    """Return symbols called by `symbol_name`, up to `depth` levels."""
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               s.source_text, s.signature_text
        FROM edges e
        JOIN symbols caller ON caller.id = e.caller_id AND caller.name = ?
        JOIN symbols s      ON s.id      = e.callee_id
        """,
        (symbol_name,),
    ).fetchall()
    sig_only = depth >= 1
    return [_row_to_result(row, sig_only) for row in rows]


def get_impact(conn: sqlite3.Connection, symbol_name: str) -> dict:
    """How many symbols call `symbol_name`?"""
    callers = get_callers(conn, symbol_name, depth=1)
    return {
        "symbol": symbol_name,
        "count": len(callers),
        "callers": [c.name for c in callers],
    }
