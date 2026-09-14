from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .models import ModelResponse, ToolCall


class DeepSeekChatClient:
    """DeepSeek adapter using its OpenAI-compatible Chat Completions tool API."""

    def __init__(self, model: str, base_url: str = "https://api.deepseek.com") -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
        )
        message = response.choices[0].message
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                arguments = {"_invalid_json": call.function.arguments}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        return ModelResponse(content=message.content, tool_calls=calls)


# Backward-compatible name for code that imported the first implementation.
OpenAIChatClient = DeepSeekChatClient
