import json
import re
from pathlib import Path

import click

from symbex_core.db import get_db, init_schema
from symbex_core.indexer import index_project
from symbex_core.overview import write_overview

_START = "<!-- symbex-start -->"
_END = "<!-- symbex-end -->"

_AGENT_POLICY = """\
## Symbex — Symbol-level context retrieval

Before reading any source file:
1. Call `symbex_locate("<task>")` to get the exact symbols needed.
2. Use `symbex_symbol("<name>")` instead of reading the whole file.
3. Use `symbex_callers("<name>")` to find who calls a function.
4. Use `symbex_impact("<name>")` before editing to see what breaks.

Never load a full file if symbex can answer the question.\
"""


def upsert_agent_policy(file_path: Path, content: str) -> None:
    """Write or update the symbex policy block in file_path."""
    block = f"{_START}\n{content}\n{_END}\n"
    if not file_path.exists():
        file_path.write_text(block)
        return
    text = file_path.read_text()
    if _START in text:
        new_text = re.sub(
            re.escape(_START) + r".*?" + re.escape(_END),
            block.rstrip("\n"),
            text,
            flags=re.DOTALL,
        )
        file_path.write_text(new_text)
    else:
        file_path.write_text(text.rstrip("\n") + "\n\n" + block)


def register_mcp_claude(project_root: Path, server_root: Path) -> None:
    """Register symbex in the project's .mcp.json for Claude Code."""
    mcp_file = project_root / ".mcp.json"
    data: dict = {"mcpServers": {}}
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text())
        except json.JSONDecodeError:
            pass
    data.setdefault("mcpServers", {})
    data["mcpServers"]["symbex"] = {
        "command": "symbex-mcp",
        "args": ["--root", str(server_root.resolve())],
    }
    mcp_file.write_text(json.dumps(data, indent=2))


def register_mcp_gemini(
    server_root: Path,
    gemini_config_dir: Path | None = None,
) -> None:
    """Register symbex in the Gemini/Antigravity MCP config."""
    if gemini_config_dir is None:
        gemini_config_dir = Path.home() / ".gemini" / "config"
    gemini_config_dir.mkdir(parents=True, exist_ok=True)
    gemini_file = gemini_config_dir / "mcp_config.json"
    data: dict = {"mcpServers": {}}
    if gemini_file.exists():
        try:
            data = json.loads(gemini_file.read_text())
        except json.JSONDecodeError:
            pass
    data.setdefault("mcpServers", {})
    data["mcpServers"]["symbex"] = {
        "command": "symbex-mcp",
        "args": ["--root", str(server_root.resolve())],
    }
    gemini_file.write_text(json.dumps(data, indent=2))


@click.command("init")
@click.pass_context
def init_cmd(ctx):
    """Index project, write agent policy, and register MCP server."""
    root = ctx.obj["root"]

    # A. Index
    click.echo("Indexing project...")
    conn = get_db(root)
    init_schema(conn)
    stats = index_project(root, conn)
    click.echo(
        f"Indexed {stats['symbols']} symbols, "
        f"{stats['files']} files, "
        f"{stats['edges']} edges"
    )

    # B. Overview
    overview_path = write_overview(conn, root)
    click.echo(f"Overview written to {overview_path.relative_to(root)}")

    # C. Agent policy
    for fname in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        policy_file = root / fname
        upsert_agent_policy(policy_file, _AGENT_POLICY)
        click.echo(f"Agent policy written to {fname}")

    # D. MCP registration
    register_mcp_claude(root, server_root=root)
    click.echo("MCP server registered in .mcp.json")

    register_mcp_gemini(server_root=root)
    click.echo("MCP server registered in ~/.gemini/config/mcp_config.json")

    click.echo("Done. Restart your agent IDE to load the MCP server.")
