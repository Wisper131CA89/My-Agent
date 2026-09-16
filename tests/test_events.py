import json
from pathlib import Path

from mini_agent.events import EventLogger, ToolEvent


def test_event_logger_writes_only_safe_tool_metadata(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    EventLogger(tmp_path, path).tool_result(ToolEvent("read_file", True, 12, "completed"))
    entry = json.loads(path.read_text(encoding="utf-8"))
    assert entry["tool"] == "read_file"
    assert entry["duration_ms"] == 12
    assert "arguments" not in entry
    assert "content" not in entry


def test_disabled_event_logger_does_not_write(tmp_path: Path) -> None:
    EventLogger(tmp_path, None).tool_result(ToolEvent("read_file", True, 1, "completed"))
    assert list(tmp_path.iterdir()) == []


def test_event_logger_io_failure_does_not_propagate(tmp_path: Path, monkeypatch) -> None:
    logger = EventLogger(tmp_path, tmp_path / "events.jsonl")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", fail)
    logger.tool_result(ToolEvent("read_file", True, 1, "completed"))


def test_event_logger_refuses_a_final_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jsonl"
    path = tmp_path / "events.jsonl"
    try:
        path.symlink_to(outside)
    except OSError:
        return
    EventLogger(tmp_path, path).tool_result(ToolEvent("read_file", True, 1, "completed"))
    assert not outside.exists()
