import json
import re
from pathlib import Path

import click

from symbex_core.db import get_db, init_schema
from symbex_core.indexer import index_project
from symbex_core.knowledge import write_knowledge
from symbex_core.overview import write_overview

_START = "<!-- symbex-start -->"
_END = "<!-- symbex-end -->"

_AGENT_POLICY = """\
## Symbex — Symbol-graph retrieval

This project is indexed by Symbex (`.symbex/` exists). Use Symbex MCP tools
BEFORE Grep, Glob, or Read when you need to find or understand code.

| Instead of | Use |
|---|---|
| Grep + Read to find code | `symbex_locate("<task>")` |
| Read to view a function | `symbex_symbol("<name>")` |
| Grep to find callers | `symbex_callers("<name>")` |
| Grep to find callees | `symbex_callees("<name>")` |
| Guessing what breaks | `symbex_impact("<name>")` before any edit |
| Reading files for project context | `symbex_knowledge()` at start of task |

After `git pull`: run `symbex index` to sync the index.
Never load a full file if symbex can answer with a symbol span.\
"""

_GLOBAL_POLICY = """\
## Symbex

In repositories with a `.symbex/` directory, use `symbex_*` MCP tools BEFORE
Grep, Glob, or Read when you need to locate or understand code:
- `symbex_knowledge()` — full project context at the start of a task
- `symbex_locate("<task>")` — find relevant symbols (replaces grep + read)
- `symbex_symbol("<name>")` — get a function's source span
- `symbex_callers` / `symbex_callees` — navigate the call graph
- `symbex_impact("<name>")` — check what breaks before editing\
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


def register_global_claude(global_claude_dir: Path | None = None) -> Path:
    """Write/update Symbex trigger policy in ~/.claude/CLAUDE.md."""
    if global_claude_dir is None:
        global_claude_dir = Path.home() / ".claude"
    global_claude_dir.mkdir(parents=True, exist_ok=True)
    target = global_claude_dir / "CLAUDE.md"
    upsert_agent_policy(target, _GLOBAL_POLICY)
    return target


def register_global_agents_md(global_dir: Path | None = None) -> Path:
    """Write/update Symbex trigger policy in ~/.agents/AGENTS.md."""
    if global_dir is None:
        global_dir = Path.home() / ".agents"
    global_dir.mkdir(parents=True, exist_ok=True)
    target = global_dir / "AGENTS.md"
    upsert_agent_policy(target, _GLOBAL_POLICY)
    return target


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

    # B. Overview + Knowledge
    overview_path = write_overview(conn, root)
    click.echo(f"Overview written to {overview_path.relative_to(root)}")
    knowledge_path = write_knowledge(conn, root)
    click.echo(f"Project knowledge written to {knowledge_path.relative_to(root)}")

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

    # E. Global agent policies
    global_claude = register_global_claude()
    click.echo(f"Global policy written to {global_claude}")

    global_agents = register_global_agents_md()
    click.echo(f"Global policy written to {global_agents}")

    click.echo("Done. Restart your agent IDE to load the MCP server.")
