from pathlib import Path

import pytest

from mini_agent.cli import _make_config, build_parser


def test_cli_mode_overrides_file_run_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_file = tmp_path / "agent.toml"
    config_file.write_text("[agent]\nworkspace = 'workspace'\nmode = 'run'\n")

    args = build_parser().parse_args(["--config", str(config_file), "--mode", "read"])

    config = _make_config(args)
    assert config.mode == "read"
    assert not config.allow_run


def test_cli_mode_overrides_toml_legacy_allow_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_file = tmp_path / "agent.toml"
    config_file.write_text("[agent]\nworkspace = 'workspace'\nallow_run = true\n")

    args = build_parser().parse_args(["--config", str(config_file), "--mode", "read"])

    config = _make_config(args)
    assert config.mode == "read"
    assert not config.allow_run


def test_allow_run_and_explicit_mode_are_cli_conflict() -> None:
    args = build_parser().parse_args(["--mode", "read", "--allow-run"])
    with pytest.raises(ValueError, match="cannot be combined"):
        _make_config(args)


def test_list_skills_is_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mini_agent import cli

    class ForbiddenMCP:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("offline listing must not connect MCP")

    monkeypatch.setattr("mini_agent.mcp.MCPClient", ForbiddenMCP)
    cli.main(["--list-skills"])
    assert "list_files" in capsys.readouterr().out


def test_missing_api_key_has_a_specific_safe_startup_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mini_agent import cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SystemExit) as result:
        cli.main(["--workspace", str(tmp_path)])

    assert result.value.code == 2
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err
