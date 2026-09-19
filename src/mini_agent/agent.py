from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from typing import Any

from .config import AgentConfig
from .events import EventLogger, ToolEvent
from .models import ModelClient, ToolCall, ToolExecution, ToolResult, TurnReport
from .planning import PlanStep, UpdatePlanTool
from .prompts import SYSTEM_PROMPT
from .tools import (
    ApplyPatchTool,
    ListFilesTool,
    ReadFileTool,
    RunCommandTool,
    SearchTextTool,
    ToolRegistry,
    WriteFileTool,
)
from .tools.base import Tool


class ReactAgent:
    def __init__(
        self,
        config: AgentConfig,
        model_client: ModelClient,
        on_action: Callable[[str], None] | None = None,
        additional_tools: Iterable[Tool] = (),
    ) -> None:
        self.config = config
        self.model_client = model_client
        self.on_action = on_action or (lambda _: None)
        self.plan: list[PlanStep] = []
        builtin_tools: list[Tool] = [
            ListFilesTool(config.workspace),
            ReadFileTool(config.workspace),
            SearchTextTool(config.workspace),
            WriteFileTool(config.workspace),
            ApplyPatchTool(config.workspace),
            RunCommandTool(
                config.workspace,
                enabled=config.mode == "run",
                max_output_chars=config.max_tool_output_chars,
            ),
            UpdatePlanTool(config.workspace, self._set_plan),
        ]
        builtin_tools.extend(additional_tools)
        self.registry = ToolRegistry(
            builtin_tools,
            max_output_chars=config.max_tool_output_chars,
            mode=config.mode,
        )
        self.events = EventLogger(config.workspace, config.log_runs)
        self.clear()

    def _set_plan(self, steps: list[PlanStep]) -> None:
        self.plan = steps
        if self.config.show_plan:
            self._safe_action("公开计划：\n" + self.plan_text())

    def plan_text(self) -> str:
        if not self.plan:
            return "暂无公开计划。"
        return "\n".join(f"- [{step.status}] {step.description}" for step in self.plan)

    def clear(self) -> None:
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{SYSTEM_PROMPT}\nConfigured workspace: {self.config.workspace}"
                    f"\nActive capability mode: {self.config.mode}."
                ),
            }
        ]
        self.plan = []
        self.last_turn = TurnReport(None, False, (), "cleared")

    def _safe_action(self, text: str) -> None:
        try:
            self.on_action(text)
        except Exception:  # noqa: BLE001 - callbacks are arbitrary UI integrations.
            # A terminal/UI observer must not corrupt the conversation protocol.
            return

    def _safe_tool_name(self, call: ToolCall) -> str:
        return (
            call.name
            if isinstance(call.name, str) and call.name in self.registry._allowed
            else "unrecognized_tool"
        )

    @staticmethod
    def _summary(tool: str, result: ToolResult) -> str:
        if not result.success:
            return result.error_code or "failed"
        if tool in {"write_file", "apply_patch"}:
            return "file updated"
        if tool in {"list_files", "read_file", "search_text"}:
            count = 0 if not result.content else result.content.count("\n") + 1
            return f"inspection completed ({min(count, 999)} entries)"
        if tool == "run_command":
            match = re.search(r"(?:^|\n)exit_code=(\d+)", result.content)
            return f"command exit {match.group(1)}" if match else "command completed"
        return "completed"

    def _append_tool_result(
        self, call: ToolCall, result: ToolResult, duration_ms: int, step: int
    ) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": self.registry.message_content(result),
            }
        )
        safe_tool = self._safe_tool_name(call)
        summary = self._summary(safe_tool, result)
        self.events.tool_result(
            ToolEvent(safe_tool, result.success, duration_ms, summary, result.error_code)
        )
        self._safe_action(f"步骤 {step}：{safe_tool} — {summary}（{duration_ms}ms）")
        self._record(call, result)

    def _record(self, call: ToolCall, result: ToolResult) -> None:
        self._turn_tools.append(
            ToolExecution(
                self._safe_tool_name(call),
                result.success,
                result.error_code,
                result.error_code == "cancelled",
            )
        )

    def _cancel_remaining(self, calls: list[ToolCall], reason: str, step: int) -> None:
        for call in calls:
            self._append_tool_result(call, ToolResult(False, reason, "cancelled", False), 0, step)

    def run_turn(self, user_input: str) -> str:
        if not user_input.strip():
            return "请输入一个任务。"
        # A public plan describes one submitted task only; never carry an old
        # model-reported "completed" step into a distinct user request.
        self.plan = []
        self.messages.append({"role": "user", "content": user_input})
        self._turn_tools: list[ToolExecution] = []

        def finish(text: str, model_replied: bool, stop_reason: str) -> str:
            # A plan update is bookkeeping, not evidence that a requested
            # external action succeeded.
            actual = [item for item in self._turn_tools if item.name != "update_plan"]
            executed = bool(actual) and all(item.success for item in actual)
            self.last_turn = TurnReport(
                text if model_replied else None, executed, tuple(self._turn_tools), stop_reason
            )
            return text

        consecutive_errors = 0
        for step in range(1, self.config.max_steps + 1):
            try:
                response = self.model_client.complete(self.messages, self.registry.schemas())
            except KeyboardInterrupt:
                return finish("模型调用已取消；会话仍可继续。", False, "model_cancelled")
            except Exception:  # noqa: BLE001 - model providers expose varied transport errors.
                # Keep only the valid user message; do not leave a partial assistant call behind.
                return finish("模型调用失败；会话仍可继续，请稍后重试。", False, "model_failed")
            assistant: dict[str, Any] = {"role": "assistant", "content": response.content}
            if response.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in response.tool_calls
                ]
            self.messages.append(assistant)
            if not response.tool_calls:
                return finish(response.content or "模型没有返回可显示的内容。", True, "completed")
            for index, call in enumerate(response.tool_calls):
                self._safe_action(f"步骤 {step}：调用工具 {self._safe_tool_name(call)}")
                started = time.monotonic()
                try:
                    result = self.registry.execute(call.name, call.arguments)
                except KeyboardInterrupt:
                    self._append_tool_result(
                        call,
                        ToolResult(False, "工具执行已取消。", "cancelled", False),
                        int((time.monotonic() - started) * 1000),
                        step,
                    )
                    self._cancel_remaining(
                        response.tool_calls[index + 1 :], "因用户取消而未执行。", step
                    )
                    return finish("工具执行已取消；会话仍可继续。", False, "tool_cancelled")
                self._append_tool_result(
                    call, result, int((time.monotonic() - started) * 1000), step
                )
                consecutive_errors = 0 if result.success else consecutive_errors + 1
                if consecutive_errors >= self.config.max_consecutive_errors:
                    self._cancel_remaining(
                        response.tool_calls[index + 1 :], "连续工具错误达到上限而未执行。", step
                    )
                    return finish(
                        "连续工具错误达到上限，Agent 已安全停止。请检查最后几条工具错误。",
                        False,
                        "error_limit",
                    )
        return finish(
            f"达到最大步骤数 {self.config.max_steps}，Agent 已安全停止。", False, "max_steps"
        )
