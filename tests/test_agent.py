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
        ModelResponse(tool_calls=[ToolCall(f"call-{index}", "missing", {})]) for index in range(3)
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


def test_read_mode_neither_exposes_nor_executes_edit_tools(tmp_path: Path) -> None:
    agent = ReactAgent(AgentConfig(workspace=tmp_path, mode="read"), FakeModel([]))
    names = {schema["function"]["name"] for schema in agent.registry.schemas()}
    assert "write_file" not in names
    assert (
        agent.registry.execute("write_file", {"path": "x", "content": "x"}).error_code
        == "tool_not_permitted"
    )


def test_model_failure_keeps_valid_continuation(tmp_path: Path) -> None:
    class FlakyModel:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("private token must not be shown")
            return ModelResponse(content="recovered")

    agent = ReactAgent(AgentConfig(workspace=tmp_path), FlakyModel())
    assert "失败" in agent.run_turn("first")
    assert agent.messages[-1] == {"role": "user", "content": "first"}
    assert agent.run_turn("second") == "recovered"


def test_error_limit_cancels_all_remaining_calls(tmp_path: Path) -> None:
    response = ModelResponse(
        tool_calls=[ToolCall("one", "missing", {}), ToolCall("two", "missing", {})]
    )
    agent = ReactAgent(
        AgentConfig(workspace=tmp_path, max_consecutive_errors=1), FakeModel([response])
    )
    assert "安全停止" in agent.run_turn("bad calls")
    tools = [message for message in agent.messages if message["role"] == "tool"]
    assert len(tools) == 2
    assert "cancelled" in tools[-1]["content"]


def test_untrusted_tool_name_and_callback_failure_do_not_break_tool_results(tmp_path: Path) -> None:
    response = ModelResponse(tool_calls=[ToolCall("one", "bad\\nname", {})])
    actions: list[str] = []

    def broken_callback(text: str) -> None:
        actions.append(text)
        raise RuntimeError("terminal failure")

    agent = ReactAgent(
        AgentConfig(workspace=tmp_path, max_steps=1), FakeModel([response]), broken_callback
    )
    assert "最大步骤数" in agent.run_turn("call tool")
    assert len([message for message in agent.messages if message["role"] == "tool"]) == 1
    assert "unrecognized_tool" in actions[0]
