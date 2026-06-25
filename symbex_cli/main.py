import sys
from pathlib import Path

import click

from symbex_core.db import get_db, get_index_version, init_schema
from symbex_core.graph import get_callers, get_callees, get_impact
from symbex_core.indexer import index_project
from symbex_core.knowledge import write_knowledge
from symbex_core.retrieval import locate, search_bm25


def _open_db(root: Path):
    conn = get_db(root)
    init_schema(conn)
    return conn


def _fmt_line_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def _fmt_symbol_header(name: str, kind: str, file_path: str,
                        start: int, end: int, tokens: int | None = None) -> str:
    loc = f"{file_path}:{_fmt_line_range(start, end)}"
    tok_str = f", {tokens} tokens" if tokens is not None else ""
    return f"{loc}  {name}  ({kind}{tok_str})"


@click.group()
@click.option("--root", default=".", show_default=True,
              type=click.Path(exists=False), help="Project root directory.")
@click.pass_context
def cli(ctx, root):
    ctx.ensure_object(dict)
    ctx.obj["root"] = Path(root).resolve()


@cli.command("index")
@click.pass_context
def index_cmd(ctx):
    """Rebuild the symbol index."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    stats = index_project(root, conn)
    click.echo(
        f"Indexed {stats['symbols']} symbols, "
        f"{stats['files']} files, "
        f"{stats['edges']} edges"
    )


@cli.command("locate")
@click.argument("task")
@click.option("--budget", default=2000, show_default=True, help="Token budget.")
@click.pass_context
def locate_cmd(ctx, task, budget):
    """Find relevant symbols for TASK within budget tokens."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    results = locate(conn, task, budget)
    if not results:
        click.echo("No symbols found.")
        return
    total = 0
    for r in results:
        click.echo(_fmt_symbol_header(r.name, r.kind, r.file_path,
                                      r.start_line, r.end_line, r.token_estimate))
        click.echo(r.text)
        click.echo()
        total += r.token_estimate
    click.echo(f"Total: {len(results)} symbols, {total} tokens")


@cli.command("symbol")
@click.argument("name")
@click.pass_context
def symbol_cmd(ctx, name):
    """Print the full source of the named symbol."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    row = conn.execute(
        "SELECT name, kind, file_path, start_line, end_line, source_text "
        "FROM symbols WHERE name = ? LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        click.echo(f"Error: symbol '{name}' not found", err=True)
        sys.exit(1)
    click.echo(_fmt_symbol_header(row[0], row[1], row[2], row[3], row[4]))
    click.echo(row[5])


@cli.command("callers")
@click.argument("name")
@click.option("--depth", default=1, show_default=True)
@click.pass_context
def callers_cmd(ctx, name, depth):
    """Show symbols that call NAME."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    results = get_callers(conn, name, depth)
    click.echo(f"Callers of '{name}' ({len(results)}):")
    for r in results:
        sites_str = (
            "  called at lines: " + ", ".join(str(s) for s in r.call_sites[:8])
            if r.call_sites else ""
        )
        click.echo(
            f"  {r.file_path}:{r.start_line}  {r.name}  ({r.kind}, {r.call_count}x)"
        )
        if sites_str:
            click.echo(f"  {sites_str}")
        click.echo(f"  {r.text}")
        click.echo()


@cli.command("callees")
@click.argument("name")
@click.option("--depth", default=1, show_default=True)
@click.pass_context
def callees_cmd(ctx, name, depth):
    """Show symbols called by NAME."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    results = get_callees(conn, name, depth)
    click.echo(f"Callees of '{name}' ({len(results)}):")
    for r in results:
        sites_str = (
            "  called at lines: " + ", ".join(str(s) for s in r.call_sites[:8])
            if r.call_sites else ""
        )
        click.echo(
            f"  {r.file_path}:{r.start_line}  {r.name}  ({r.kind}, {r.call_count}x)"
        )
        if sites_str:
            click.echo(f"  {sites_str}")
        click.echo(f"  {r.text}")
        click.echo()


@cli.command("impact")
@click.argument("name")
@click.pass_context
def impact_cmd(ctx, name):
    """Show how many callers are affected by changing NAME."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    impact = get_impact(conn, name)
    click.echo(f"'{name}' affects {impact['count']} callers:")
    for c in impact["callers"]:
        loc = f"{c['file_path']}:{c['start_line']}"
        sites_str = (
            "  lines: " + ", ".join(str(s) for s in c["call_sites"][:8])
            if c["call_sites"] else ""
        )
        click.echo(f"  {loc}  {c['name']}  ({c['call_count']}x){sites_str}")


@cli.command("preview")
@click.argument("task")
@click.pass_context
def preview_cmd(ctx, task):
    """Show token cost per symbol without loading full source."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    results = search_bm25(conn, task, limit=10)
    if not results:
        click.echo("No symbols found.")
        return
    click.echo("Symbol preview (token costs):")
    total = 0
    for r in results:
        click.echo(
            f"  {r.name:<30} {r.kind:<10} "
            f"{r.file_path}:{r.start_line:<6} ~{r.token_estimate} tokens"
        )
        total += r.token_estimate
    click.echo(f"\nTotal if loaded: ~{total} tokens")


@cli.command("tests")
@click.argument("name")
@click.pass_context
def tests_cmd(ctx, name):
    """Show test symbols referencing NAME."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    rows = conn.execute(
        "SELECT name, kind, file_path, start_line, end_line "
        "FROM symbols WHERE is_test = 1 AND source_text LIKE ? "
        "ORDER BY name",
        (f"%{name}%",),
    ).fetchall()
    click.echo(f"Test symbols referencing '{name}' ({len(rows)}):")
    for row in rows:
        click.echo(
            f"  {row[2]}:{_fmt_line_range(row[3], row[4])}  {row[0]}  ({row[1]})"
        )


@cli.command("status")
@click.pass_context
def status_cmd(ctx):
    """Show index statistics."""
    root = ctx.obj["root"]
    db_path = root / ".symbex" / "symbex.db"
    if not db_path.exists():
        click.echo("Not indexed. Run: symbex index")
        return
    conn = get_db(root)
    version = get_index_version(conn)
    sym_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    click.echo(f"Index:    {db_path}")
    click.echo(f"Symbols:  {sym_count}")
    click.echo(f"Files:    {file_count}")
    click.echo(f"Edges:    {edge_count}")
    click.echo(f"Version:  {version}")


@cli.command("knowledge")
@click.pass_context
def knowledge_cmd(ctx):
    """Generate project knowledge: architecture, business logic, conventions."""
    root = ctx.obj["root"]
    conn = _open_db(root)
    out = write_knowledge(conn, root)
    click.echo(f"Project knowledge written to {out}")


from symbex_cli.init import init_cmd
cli.add_command(init_cmd)
