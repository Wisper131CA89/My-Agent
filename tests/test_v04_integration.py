from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_agent.agent import ReactAgent
from mini_agent.cli import _handle_state_command, _make_config, build_parser, main
from mini_agent.config import AgentConfig
from mini_agent.models import ModelResponse, ToolCall


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = iter(responses)

    def complete(self, messages, tools) -> ModelResponse:  # type: ignore[no-untyped-def]
        return next(self._responses)


def test_saved_memory_is_found_by_a_fresh_agent_model(tmp_path: Path) -> None:
    first = ReactAgent(AgentConfig(workspace=tmp_path, memory_enabled=True), FakeModel([]))
    first.memory_store.remember("优先运行小范围测试", source="user")  # type: ignore[union-attr]

    second = ReactAgent(
        AgentConfig(workspace=tmp_path, mode="read", memory_enabled=True),
        FakeModel(
            [
                ModelResponse(
                    tool_calls=[ToolCall("memory-1", "search_memory", {"query": "测试"})]
                ),
                ModelResponse(content="已读取历史资料。"),
            ]
        ),
    )

    assert second.run_turn("寻找已保存的经验") == "已读取历史资料。"
    result = json.loads(second.messages[-2]["content"])
    assert result["success"]
    assert "优先运行小范围测试" in result["content"]
    names = {item["function"]["name"] for item in second.registry.schemas()}
    assert {"search_memory", "list_recipes"} <= names
    assert "run_recipe" not in names


def test_verified_recipe_runs_through_model_and_is_turn_evidence(tmp_path: Path) -> None:
    setup = ReactAgent(
        AgentConfig(workspace=tmp_path, mode="run", memory_enabled=True), FakeModel([])
    )
    recipes = setup.recipe_manager
    assert recipes is not None
    (tmp_path / "test_smoke.py").write_text("def test_smoke():\n    assert 2 + 2 == 4\n")
    recipes.create(
        "inspect_then_test",
        [
            {"tool": "read_file", "arguments": {"path": "test_smoke.py"}},
            {
                "tool": "run_command",
                "arguments": {"command": ["python", "-m", "pytest", "-q", "test_smoke.py"]},
            },
        ],
    )
    assert recipes.verify("inspect_then_test").success

    restarted = ReactAgent(
        AgentConfig(workspace=tmp_path, mode="run", memory_enabled=True),
        FakeModel(
            [
                ModelResponse(
                    tool_calls=[ToolCall("recipe-1", "run_recipe", {"name": "inspect_then_test"})]
                ),
                ModelResponse(content="配方已运行。"),
            ]
        ),
    )
    assert restarted.run_turn("运行已验证的配方") == "配方已运行。"
    assert restarted.last_turn.executed_success
    assert restarted.last_turn.tools[0].name == "run_recipe"
    assert restarted.last_turn.tools[0].success


def test_memory_config_override_and_offline_listing_create_no_state(tmp_path: Path) -> None:
    config_file = tmp_path / "agent.toml"
    config_file.write_text(f"[agent]\nworkspace = {str(tmp_path)!r}\nmemory_enabled = true\n")
    args = build_parser().parse_args(["--config", str(config_file), "--no-memory"])
    assert not _make_config(args).memory_enabled

    main(["--workspace", str(tmp_path), "--memory", "--list-skills"])
    assert not (tmp_path / ".mini-agent").exists()

    config_file.write_text(f"[agent]\nworkspace = {str(tmp_path)!r}\nmemory_enabled = 'yes'\n")
    invalid = build_parser().parse_args(["--config", str(config_file)])
    with pytest.raises(ValueError, match="配置文件"):
        _make_config(invalid)


def test_memory_cli_is_explicit_and_save_task_excludes_model_final(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    disabled = ReactAgent(AgentConfig(workspace=tmp_path), FakeModel([]))
    assert _handle_state_command(disabled, "/remember no state")
    assert not (tmp_path / ".mini-agent").exists()

    agent = ReactAgent(
        AgentConfig(workspace=tmp_path, memory_enabled=True),
        FakeModel([ModelResponse(content="FINAL_CODE_MUST_NOT_BE_SAVED")]),
    )
    agent.run_turn("ordinary prompt is not automatically saved")
    assert not (tmp_path / ".mini-agent").exists()
    assert _handle_state_command(agent, "/save-task completed small check")
    saved = agent.memory_store.search("completed")  # type: ignore[union-attr]
    assert len(saved) == 1
    assert "FINAL_CODE_MUST_NOT_BE_SAVED" not in saved[0]["text"]
    assert "ordinary prompt" not in saved[0]["text"]

    readonly = ReactAgent(
        AgentConfig(workspace=tmp_path, mode="read", memory_enabled=True), FakeModel([])
    )
    assert _handle_state_command(readonly, "/remember rejected")
    assert "只读模式" in capsys.readouterr().out


def test_recipe_cli_interrupt_is_safely_consumed(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    agent = ReactAgent(AgentConfig(workspace=tmp_path, memory_enabled=True), FakeModel([]))
    manager = agent.recipe_manager
    assert manager is not None

    def interrupted(name: str) -> None:
        raise KeyboardInterrupt

    manager.verify = interrupted  # type: ignore[method-assign]
    assert _handle_state_command(agent, "/recipe-verify any_recipe")
    assert "已取消" in capsys.readouterr().out
