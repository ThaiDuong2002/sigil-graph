import argparse
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from symbex_core.cache import QueryCache
from symbex_core.db import get_db, init_schema
from symbex_core.graph import get_callers, get_callees, get_impact
from symbex_core.indexer import index_project
from symbex_core.retrieval import SymbolResult, locate, search_bm25

mcp = FastMCP("symbex")

_root: Path = Path.cwd()
_conn: sqlite3.Connection | None = None
_cache: QueryCache = QueryCache()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = get_db(_root)
        init_schema(_conn)
    _cache.invalidate_if_stale(_conn)
    return _conn


# ---------------------------------------------------------------------------
# Helper functions (module-level so tests can import them)
# ---------------------------------------------------------------------------

def _result_to_dict(r: SymbolResult) -> dict:
    return {
        "name": r.name,
        "kind": r.kind,
        "file_path": r.file_path,
        "start_line": r.start_line,
        "end_line": r.end_line,
        "text": r.text,
        "is_signature_only": r.is_signature_only,
        "token_estimate": r.token_estimate,
        "score": r.score,
        "call_count": r.call_count,
        "call_sites": r.call_sites,
    }


def _locate_symbols(
    conn: sqlite3.Connection, task: str, budget: int = 2000, cache=None
) -> dict:
    results = locate(conn, task, budget, cache)
    return {
        "symbols": [_result_to_dict(r) for r in results],
        "total_tokens": sum(r.token_estimate for r in results),
    }


def _get_symbol(conn: sqlite3.Connection, name: str) -> dict:
    row = conn.execute(
        "SELECT name, kind, file_path, start_line, end_line, source_text "
        "FROM symbols WHERE name = ? LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        return {"error": f"symbol '{name}' not found"}
    return {
        "name": row[0],
        "kind": row[1],
        "file_path": row[2],
        "start_line": row[3],
        "end_line": row[4],
        "text": row[5],
    }


def _get_callers_result(
    conn: sqlite3.Connection, name: str, depth: int = 1
) -> dict:
    results = get_callers(conn, name, depth)
    return {
        "name": name,
        "callers": [_result_to_dict(r) for r in results],
        "count": len(results),
    }


def _get_callees_result(
    conn: sqlite3.Connection, name: str, depth: int = 1
) -> dict:
    results = get_callees(conn, name, depth)
    return {
        "name": name,
        "callees": [_result_to_dict(r) for r in results],
        "count": len(results),
    }


def _preview_symbols(conn: sqlite3.Connection, task: str, limit: int = 10) -> dict:
    results = search_bm25(conn, task, limit=limit)
    symbols = [
        {
            "name": r.name,
            "kind": r.kind,
            "file_path": r.file_path,
            "start_line": r.start_line,
            "end_line": r.end_line,
            "token_estimate": r.token_estimate,
            "score": r.score,
        }
        for r in results
    ]
    return {
        "symbols": symbols,
        "total_tokens": sum(r.token_estimate for r in results),
    }


def _get_impact_result(conn: sqlite3.Connection, name: str) -> dict:
    impact = get_impact(conn, name)
    return {
        "symbol": impact["symbol"],
        "caller_count": impact["count"],
        "callers": impact["callers"],  # already list[str] from get_impact
    }


def _run_index(root: Path) -> dict:
    conn = get_db(root)
    init_schema(conn)
    return index_project(root, conn)


def _get_tests(conn: sqlite3.Connection, name: str) -> dict:
    rows = conn.execute(
        "SELECT name, kind, file_path, start_line, end_line, source_text "
        "FROM symbols WHERE is_test = 1 AND source_text LIKE ? "
        "ORDER BY name",
        (f"%{name}%",),
    ).fetchall()
    tests = [
        {
            "name": r[0],
            "kind": r[1],
            "file_path": r[2],
            "start_line": r[3],
            "end_line": r[4],
            "text": r[5],
        }
        for r in rows
    ]
    return {"name": name, "tests": tests, "count": len(tests)}


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def symbex_locate(task: str, budget: int = 2000) -> dict:
    """Find the minimal set of symbols relevant to a task within a token budget."""
    return _locate_symbols(_get_conn(), task, budget, _cache)


@mcp.tool()
def symbex_symbol(name: str) -> dict:
    """Return the full source span of a named symbol."""
    return _get_symbol(_get_conn(), name)


@mcp.tool()
def symbex_callers(name: str, depth: int = 1) -> dict:
    """Return all symbols that call the named symbol."""
    return _get_callers_result(_get_conn(), name, depth)


@mcp.tool()
def symbex_callees(name: str, depth: int = 1) -> dict:
    """Return all symbols called by the named symbol."""
    return _get_callees_result(_get_conn(), name, depth)


@mcp.tool()
def symbex_preview(task: str) -> dict:
    """Return token cost estimates per symbol without loading full source."""
    return _preview_symbols(_get_conn(), task)


@mcp.tool()
def symbex_impact(name: str) -> dict:
    """Return the count and list of callers affected by changing this symbol."""
    return _get_impact_result(_get_conn(), name)


@mcp.tool()
def symbex_index(path: str = ".") -> dict:
    """Rebuild the symbol index for the given project path."""
    root = Path(path).resolve() if path != "." else _root
    return _run_index(root)


@mcp.tool()
def symbex_tests(name: str) -> dict:
    """Return test symbols whose source references the named symbol."""
    return _get_tests(_get_conn(), name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global _root
    parser = argparse.ArgumentParser(description="Symbex MCP server")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args, _ = parser.parse_known_args()
    _root = args.root.resolve()
    mcp.run()


if __name__ == "__main__":
    main()
