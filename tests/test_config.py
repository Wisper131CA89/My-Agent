from pathlib import Path

import pytest

from mini_agent.config import AgentConfig, load_config


def test_toml_log_path_is_resolved_inside_its_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_file = tmp_path / "agent.toml"
    config_file.write_text("[agent]\nworkspace = 'workspace'\nlog_runs = 'runs/events.jsonl'\n")

    config = load_config(config_file)

    assert config.log_runs == workspace / "runs" / "events.jsonl"


def test_cli_workspace_override_precedes_invalid_toml_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "valid"
    workspace.mkdir()
    config_file = tmp_path / "agent.toml"
    config_file.write_text("[agent]\nworkspace = 'does-not-exist'\n")

    assert load_config(config_file, {"workspace": workspace}).workspace == workspace.resolve()


@pytest.mark.parametrize("field", ["max_steps", "max_consecutive_errors", "max_tool_output_chars"])
def test_numeric_config_values_do_not_accept_booleans(tmp_path: Path, field: str) -> None:
    values = {field: True}
    with pytest.raises(ValueError):
        AgentConfig(workspace=tmp_path, **values)  # type: ignore[arg-type]
