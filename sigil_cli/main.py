import importlib.metadata
import subprocess
import sys
from pathlib import Path

import click

from sigil_core.db import get_db, get_index_version, init_schema, rebuild_fts
from sigil_core.graph import get_callers, get_callees, get_impact
from sigil_core.indexer import index_project
from sigil_core.knowledge import write_knowledge
from sigil_core.retrieval import locate, search_bm25

try:
    _version = importlib.metadata.version("sigil")
except importlib.metadata.PackageNotFoundError:
    _version = "dev"


def _find_install_dir() -> Path | None:
    """Return the sigil git clone root, or None if not an editable git install."""
    import sigil_core
    candidate = Path(sigil_core.__file__).parent.parent
    if (candidate / ".git").exists():
        return candidate
    return None


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
@click.version_option(version=_version, prog_name="sigil")
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

    files_changed = stats.get("files_changed", 0)
    removed       = stats.get("removed", [])

    if files_changed == 0 and not removed:
        sym_total = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        click.echo(
            f"Up to date — {sym_total} symbols, "
            f"{stats['files']} files, "
            f"{stats['edges']} edges"
        )
        return

    click.echo(
        f"Indexed {stats['symbols']} new symbols across {files_changed} file(s), "
        f"{stats['files']} files total, "
        f"{stats['edges']} edges"
    )

    def _show(marker: str, names: list) -> None:
        if not names:
            return
        MAX = 6
        preview = ", ".join(names[:MAX])
        extra   = f" … +{len(names) - MAX} more" if len(names) > MAX else ""
        click.echo(f"  {marker} {len(names):>4}  {preview}{extra}")

    _show("+ new    ", stats.get("added", []))
    _show("~ changed", stats.get("changed", []))
    _show("- removed", removed)


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
    db_path = root / ".sigil" / "sigil.db"
    if not db_path.exists():
        click.echo("Not indexed. Run: sigil index")
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


@cli.command("update")
def update_cmd():
    """Update sigil to the latest version (git-based installs only)."""
    install_dir = _find_install_dir()
    if install_dir is None:
        click.echo(
            "Cannot auto-update: sigil was not installed via install.sh/install.ps1.\n"
            "  To update a pipx install:  pipx upgrade sigil-graph\n"
            "  To reinstall from source:  re-run the one-liner install script."
        )
        sys.exit(1)

    old_sha = subprocess.run(
        ["git", "-C", str(install_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    click.echo(f"Updating sigil at {install_dir} ...")

    pull = subprocess.run(
        ["git", "-C", str(install_dir), "pull"],
        capture_output=True, text=True,
    )
    if pull.returncode != 0:
        click.echo(f"git pull failed:\n{pull.stderr}", err=True)
        sys.exit(1)

    new_sha = subprocess.run(
        ["git", "-C", str(install_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    if old_sha == new_sha:
        click.echo(f"Already up to date ({old_sha}).")
        return

    scripts_dir = Path(sys.executable).parent
    pip_candidates = [scripts_dir / "pip.exe", scripts_dir / "pip"]
    pip = next((p for p in pip_candidates if p.exists()), pip_candidates[-1])
    reinstall = subprocess.run(
        [str(pip), "install", "-e", str(install_dir), "--quiet"],
        capture_output=True, text=True,
    )
    if reinstall.returncode != 0:
        click.echo(f"Reinstall failed:\n{reinstall.stderr}", err=True)
        sys.exit(1)

    click.echo(f"Updated: {old_sha} → {new_sha}")
    click.echo("Restart your shell to use the new version.")


@cli.command("summarize")
@click.option("--backend", default="auto", show_default=True,
              type=click.Choice(["auto", "ollama", "litellm"]),
              help="Summarization backend.")
@click.option("--force", is_flag=True, default=False,
              help="Re-summarize symbols that already have summaries.")
@click.pass_context
def summarize_cmd(ctx, backend, force):
    """Generate AI summaries for symbols to improve semantic search.

    Backends (auto-detected in order):
      ollama   — local Ollama (localhost:11434), uses SIGIL_OLLAMA_MODEL env var
      litellm  — any provider via LiteLLM: set SIGIL_LLM_MODEL + SIGIL_LLM_API_KEY

    Examples:
      sigil summarize                              # auto-detect
      sigil summarize --backend ollama             # force Ollama
      SIGIL_LLM_MODEL=gemini/gemini-2.0-flash-lite sigil summarize --backend litellm
    """
    from sigil_core.summarizer import detect_backend, summarize as _summarize

    root = ctx.obj["root"]
    conn = _open_db(root)

    resolved = backend if backend != "auto" else detect_backend()
    if resolved is None:
        click.echo(
            "No summarization backend available. Configure one of:\n"
            "  • Ollama:  install Ollama, then: ollama pull qwen2.5:0.5b\n"
            "  • Any LLM: set SIGIL_LLM_MODEL=<provider/model> "
            "and SIGIL_LLM_API_KEY=<key>\n"
            "    Examples: gemini/gemini-2.0-flash-lite  deepseek/deepseek-chat  "
            "anthropic/claude-haiku-4-5"
        )
        sys.exit(1)

    click.echo(f"Backend: {resolved}")

    query = (
        "SELECT id, name, kind, source_text FROM symbols ORDER BY id"
        if force else
        "SELECT id, name, kind, source_text FROM symbols WHERE summary = '' ORDER BY id"
    )
    rows = conn.execute(query).fetchall()
    total = len(rows)
    if total == 0:
        click.echo("All symbols already summarized. Use --force to redo.")
        return

    click.echo(f"Summarizing {total} symbols...")
    done = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        sym_id, name, kind, source_text = row[0], row[1], row[2], row[3]
        summary = _summarize(name, kind, source_text, backend=resolved)
        if summary:
            conn.execute("UPDATE symbols SET summary=? WHERE id=?", (summary, sym_id))
            conn.commit()
            done += 1
        else:
            failed += 1
        click.echo(f"  [{i}/{total}] {name}")

    rebuild_fts(conn)
    msg = f"Done. Summarized {done}/{total} symbols."
    if failed:
        msg += f" ({failed} failed — check backend availability)"
    click.echo(msg)
    click.echo("FTS index rebuilt — semantic search is now enriched.")


from sigil_cli.init import init_cmd
cli.add_command(init_cmd)
