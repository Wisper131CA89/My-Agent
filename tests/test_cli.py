from pathlib import Path

import pytest

from mini_agent.config import AgentConfig


def test_allow_run_is_compatibility_alias(tmp_path: Path) -> None:
    assert AgentConfig(workspace=tmp_path, allow_run=True).mode == "run"


def test_allow_run_conflicts_with_explicit_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        AgentConfig(workspace=tmp_path, mode="read", allow_run=True)


def test_log_path_refuses_protected_or_linked_target(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="protected"):
        AgentConfig(workspace=tmp_path, log_runs=Path(".git/events.jsonl"))

    outside = tmp_path.parent / "outside.jsonl"
    log_path = tmp_path / "events.jsonl"
    try:
        log_path.symlink_to(outside)
    except OSError:
        return
    with pytest.raises(PermissionError, match="link"):
        AgentConfig(workspace=tmp_path, log_runs=log_path)
