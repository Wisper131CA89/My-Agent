from __future__ import annotations

import json
from typing import Any, Callable

from .config import AgentConfig
from .models import ModelClient
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


class ReactAgent:
    def __init__(
        self,
        config: AgentConfig,
        model_client: ModelClient,
        on_action: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.model_client = model_client
        self.on_action = on_action or (lambda _: None)
        self.registry = ToolRegistry(
            [
                ListFilesTool(config.workspace),
                ReadFileTool(config.workspace),
                SearchTextTool(config.workspace),
                WriteFileTool(config.workspace),
                ApplyPatchTool(config.workspace),
                RunCommandTool(
                    config.workspace,
                    enabled=config.allow_run,
                    max_output_chars=config.max_tool_output_chars,
                ),
            ],
            max_output_chars=config.max_tool_output_chars,
        )
        self.clear()

    def clear(self) -> None:
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": f"{SYSTEM_PROMPT}\nConfigured workspace: {self.config.workspace}",
            }
        ]

    def run_turn(self, user_input: str) -> str:
        if not user_input.strip():
            return "请输入一个任务。"
        self.messages.append({"role": "user", "content": user_input})
        consecutive_errors = 0

        for _ in range(self.config.max_steps):
            response = self.model_client.complete(self.messages, self.registry.schemas())
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
                return response.content or "模型没有返回可显示的内容。"

            for call in response.tool_calls:
                self.on_action(f"调用工具 {call.name}")
                result = self.registry.execute(call.name, call.arguments)
                consecutive_errors = 0 if result.success else consecutive_errors + 1
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": self.registry.message_content(result),
                    }
                )
                if consecutive_errors >= self.config.max_consecutive_errors:
                    return "连续工具错误达到上限，Agent 已安全停止。请检查最后几条工具错误。"

        return f"达到最大步骤数 {self.config.max_steps}，Agent 已安全停止。"

