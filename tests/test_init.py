import json
import pytest
from pathlib import Path
from symbex_core.db import get_db, init_schema
from symbex_core.indexer import index_project
from symbex_cli.init import (
    upsert_agent_policy,
    register_mcp_claude,
    register_mcp_gemini,
    register_global_claude,
    register_global_agents_md,
)


_POLICY_CONTENT = "## Symbex\nUse it.\n"
_START = "<!-- symbex-start -->"
_END = "<!-- symbex-end -->"


def test_upsert_creates_new_file(tmp_path):
    f = tmp_path / "CLAUDE.md"
    upsert_agent_policy(f, _POLICY_CONTENT)
    assert f.exists()
    text = f.read_text()
    assert _START in text
    assert _END in text
    assert "## Symbex" in text


def test_upsert_replaces_existing_block(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text(f"# Existing\n{_START}\nOld content\n{_END}\n")
    upsert_agent_policy(f, _POLICY_CONTENT)
    text = f.read_text()
    assert "Old content" not in text
    assert "## Symbex" in text
    assert text.count(_START) == 1


def test_upsert_appends_to_file_without_markers(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Existing content\n")
    upsert_agent_policy(f, _POLICY_CONTENT)
    text = f.read_text()
    assert "# Existing content" in text
    assert "## Symbex" in text


def test_register_mcp_claude_creates_file(tmp_path):
    register_mcp_claude(tmp_path, server_root=tmp_path)
    mcp_file = tmp_path / ".mcp.json"
    assert mcp_file.exists()
    data = json.loads(mcp_file.read_text())
    assert "symbex" in data["mcpServers"]
    assert data["mcpServers"]["symbex"]["command"] == "symbex-mcp"
    assert str(tmp_path) in data["mcpServers"]["symbex"]["args"]


def test_register_mcp_claude_merges_existing(tmp_path):
    mcp_file = tmp_path / ".mcp.json"
    mcp_file.write_text(json.dumps({"mcpServers": {"other": {"command": "other-mcp"}}}))
    register_mcp_claude(tmp_path, server_root=tmp_path)
    data = json.loads(mcp_file.read_text())
    assert "other" in data["mcpServers"]
    assert "symbex" in data["mcpServers"]


def test_register_mcp_gemini_creates_file(tmp_path):
    gemini_config = tmp_path / ".gemini" / "config" / "mcp_config.json"
    register_mcp_gemini(server_root=tmp_path, gemini_config_dir=tmp_path / ".gemini" / "config")
    assert gemini_config.exists()
    data = json.loads(gemini_config.read_text())
    assert "symbex" in data["mcpServers"]


def test_global_claude_creates_file(tmp_path):
    out = register_global_claude(global_claude_dir=tmp_path / ".claude")
    assert out.exists()
    text = out.read_text()
    assert ".symbex/" in text
    assert "symbex_locate" in text
    assert _START in text


def test_global_claude_is_idempotent(tmp_path):
    d = tmp_path / ".claude"
    register_global_claude(global_claude_dir=d)
    register_global_claude(global_claude_dir=d)
    text = (d / "CLAUDE.md").read_text()
    assert text.count(_START) == 1


def test_global_claude_appends_to_existing(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    (d / "CLAUDE.md").write_text("# Existing global config\n\n## CodeGraph\nUse it.\n")
    register_global_claude(global_claude_dir=d)
    text = (d / "CLAUDE.md").read_text()
    assert "# Existing global config" in text
    assert "CodeGraph" in text
    assert "symbex_locate" in text


def test_global_agents_md_creates_file(tmp_path):
    out = register_global_agents_md(global_dir=tmp_path / ".agents")
    assert out.exists()
    text = out.read_text()
    assert "symbex_locate" in text


def test_register_mcp_gemini_merges_existing(tmp_path):
    gemini_dir = tmp_path / ".gemini" / "config"
    gemini_dir.mkdir(parents=True)
    gemini_file = gemini_dir / "mcp_config.json"
    gemini_file.write_text(json.dumps({"mcpServers": {"other": {"command": "other-mcp"}}}))
    register_mcp_gemini(server_root=tmp_path, gemini_config_dir=gemini_dir)
    data = json.loads(gemini_file.read_text())
    assert "other" in data["mcpServers"]
    assert "symbex" in data["mcpServers"]
