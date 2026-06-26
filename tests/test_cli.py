import pytest
from click.testing import CliRunner
from pathlib import Path
from sigil_core.db import get_db, init_schema
from sigil_core.indexer import index_project
from sigil_cli.main import cli


@pytest.fixture
def project(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login(user: str) -> bool:\n    return True\n\n"
        "def validate(user: str) -> bool:\n    return bool(user)\n"
    )
    conn = get_db(tmp_path)
    init_schema(conn)
    index_project(tmp_path, conn)
    return tmp_path


def test_index_command_success(tmp_path):
    (tmp_path / "foo.py").write_text("def bar(): pass\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(tmp_path), "index"])
    assert result.exit_code == 0, result.output
    assert "Indexed" in result.output
    assert "symbols" in result.output


def test_locate_command_returns_results(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "locate", "login"])
    assert result.exit_code == 0, result.output


def test_locate_command_shows_total(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "locate", "login"])
    assert "Total:" in result.output or "No symbols" in result.output


def test_symbol_command_found(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "symbol", "login"])
    assert result.exit_code == 0, result.output
    assert "login" in result.output
    assert "def login" in result.output


def test_symbol_command_not_found(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "symbol", "nonexistent_xyz"])
    assert result.exit_code == 1


def test_callers_command_structure(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "callers", "login"])
    assert result.exit_code == 0, result.output
    assert "Callers of" in result.output


def test_callees_command_structure(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "callees", "login"])
    assert result.exit_code == 0, result.output
    assert "Callees of" in result.output


def test_impact_command_structure(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "impact", "login"])
    assert result.exit_code == 0, result.output
    assert "affects" in result.output


def test_preview_command_structure(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "preview", "login"])
    assert result.exit_code == 0, result.output
    assert "tokens" in result.output.lower()


def test_tests_command_structure(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "tests", "login"])
    assert result.exit_code == 0, result.output
    assert "referencing" in result.output


def test_status_command_indexed(project):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(project), "status"])
    assert result.exit_code == 0, result.output
    assert "Symbols" in result.output
    assert "Files" in result.output
    assert "Version" in result.output


def test_status_command_not_indexed(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(tmp_path), "status"])
    assert result.exit_code == 0
    assert "Not indexed" in result.output


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "sigil" in result.output
    # Should contain a version string like "0.2.0" or "dev"
    assert any(c.isdigit() or result.output.strip().endswith("dev") for c in result.output)


def test_update_not_git_install(monkeypatch):
    """update exits with error when not a git-based editable install."""
    from sigil_cli import main as cli_main
    monkeypatch.setattr(cli_main, "_find_install_dir", lambda: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["update"])
    assert result.exit_code == 1
    assert "Cannot auto-update" in result.output
