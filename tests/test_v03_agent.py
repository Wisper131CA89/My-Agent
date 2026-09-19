from pathlib import Path
from typing import ClassVar

from mini_agent.agent import ReactAgent
from mini_agent.config import AgentConfig
from mini_agent.models import ModelResponse, ToolCall, ToolResult
from mini_agent.planning import PlanStep
from mini_agent.skills import SkillSpec
from mini_agent.tools import Tool


class FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = iter(responses)

    def complete(self, messages, tools) -> ModelResponse:
        return next(self.responses)


class CustomReadTool(Tool):
    name = "custom_read"
    description = "A trusted read-only extension."
    parameters: ClassVar[dict[str, object]] = {"type": "object", "additionalProperties": False}

    def skill_spec(self) -> SkillSpec:
        return SkillSpec(
            self.name,
            self.description,
            self.parameters,
            "A short result.",
            "read",
            5,
            "1",
            [],
            "test",
        )

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(True, "extension result")


def test_custom_read_skill_is_exposed_in_read_mode(tmp_path: Path) -> None:
    agent = ReactAgent(
        AgentConfig(workspace=tmp_path, mode="read"),
        FakeModel([]),
        additional_tools=[CustomReadTool(tmp_path)],
    )
    assert "custom_read" in {item["function"]["name"] for item in agent.registry.schemas()}
    assert agent.registry.execute("custom_read", {}).success


def test_plan_only_turn_is_not_an_actual_execution_success(tmp_path: Path) -> None:
    model = FakeModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "plan",
                        "update_plan",
                        {"steps": [{"description": "Inspect files", "status": "completed"}]},
                    )
                ]
            ),
            ModelResponse(content="planned"),
        ]
    )
    agent = ReactAgent(AgentConfig(workspace=tmp_path), model)
    assert agent.run_turn("plan") == "planned"
    assert not agent.last_turn.executed_success
    assert agent.last_turn.final_response == "planned"


def test_plan_is_reset_when_a_new_task_starts(tmp_path: Path) -> None:
    model = FakeModel([ModelResponse(content="first"), ModelResponse(content="second")])
    agent = ReactAgent(AgentConfig(workspace=tmp_path), model)
    agent.plan = [PlanStep("Old task", "completed")]
    assert agent.run_turn("first task") == "first"
    assert agent.run_turn("second task") == "second"
    assert agent.plan_text() == "暂无公开计划。"


def test_cancelled_tool_is_reported_without_model_answer(tmp_path: Path) -> None:
    class InterruptingTool(CustomReadTool):
        name = "interrupting"

        def execute(self, arguments: dict[str, object]) -> ToolResult:
            raise KeyboardInterrupt

    model = FakeModel([ModelResponse(tool_calls=[ToolCall("one", "interrupting", {})])])
    agent = ReactAgent(
        AgentConfig(workspace=tmp_path), model, additional_tools=[InterruptingTool(tmp_path)]
    )
    assert "取消" in agent.run_turn("go")
    assert agent.last_turn.final_response is None
    assert agent.last_turn.stop_reason == "tool_cancelled"
    assert agent.last_turn.tools[0].cancelled
