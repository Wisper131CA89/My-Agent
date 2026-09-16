from types import SimpleNamespace

from mini_agent.llm import DeepSeekChatClient


def test_client_disables_thinking_and_safely_rejects_non_object_arguments(monkeypatch) -> None:
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            call = SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="list_files", arguments="[1, 2]"),
            )
            message = SimpleNamespace(
                content="", tool_calls=[call], reasoning_content="never log this"
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setattr("mini_agent.llm.OpenAI", FakeOpenAI)
    result = DeepSeekChatClient("test").complete([], [])
    assert captured["client"]["timeout"] == 60.0
    assert captured["client"]["max_retries"] == 2
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert result.tool_calls[0].arguments == {"_invalid_json": True}
    assert result.reasoning_content == "never log this"
