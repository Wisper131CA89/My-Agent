from pathlib import Path

from mini_agent.agent import ReactAgent
from mini_agent.config import AgentConfig
from mini_agent.models import ModelResponse, ToolCall


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = iter(responses)

    def complete(self, messages, tools) -> ModelResponse:
        return next(self.responses)


def test_agent_executes_tool_then_returns_answer(tmp_path: Path) -> None:
    model = FakeModel(
        [
            ModelResponse(tool_calls=[ToolCall("call-1", "list_files", {"path": "."})]),
            ModelResponse(content="工作目录为空。"),
        ]
    )
    agent = ReactAgent(AgentConfig(workspace=tmp_path), model)
    assert agent.run_turn("目录里有什么？") == "工作目录为空。"
    assert agent.messages[-2]["role"] == "tool"


def test_agent_stops_after_repeated_tool_errors(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall(f"call-{index}", "missing", {})])
        for index in range(3)
    ]
    agent = ReactAgent(AgentConfig(workspace=tmp_path), FakeModel(responses))
    assert "安全停止" in agent.run_turn("执行不存在的工具")


def test_agent_honors_max_steps(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall(f"call-{index}", "list_files", {})])
        for index in range(2)
    ]
    config = AgentConfig(workspace=tmp_path, max_steps=2)
    assert "最大步骤数" in ReactAgent(config, FakeModel(responses)).run_turn("一直查看目录")


def test_deepseek_is_the_default_provider_configuration(tmp_path: Path) -> None:
    config = AgentConfig(workspace=tmp_path)
    assert config.model == "deepseek-v4-flash"
    assert config.base_url == "https://api.deepseek.com"
