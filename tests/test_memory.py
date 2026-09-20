from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_agent.memory as memory_module
from mini_agent.memory import MemoryStore
from mini_agent.tools.filesystem import ReadFileTool, WriteFileTool


def test_memory_persists_across_store_instances(tmp_path: Path) -> None:
    record = MemoryStore(tmp_path).remember("用户明确保存的偏好", source="user")

    found = MemoryStore(tmp_path).search("偏好")

    assert found == [record]
    assert (
        json.loads((tmp_path / ".mini-agent" / "memory.json").read_text(encoding="utf-8"))[
            "version"
        ]
        == 1
    )


def test_read_only_store_cannot_mutate(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, writable=False)

    with pytest.raises(PermissionError):
        store.remember("no write")
    with pytest.raises(PermissionError):
        store.forget("anything")
    assert not (tmp_path / ".mini-agent").exists()


def test_reading_missing_memory_never_creates_state(tmp_path: Path) -> None:
    assert MemoryStore(tmp_path).search() == []
    assert not (tmp_path / ".mini-agent").exists()


def test_search_limit_and_forget_only_one_record(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    first = store.remember("alpha one")
    second = store.remember("alpha two", source="task")

    assert store.search("alpha", limit=1) == [second]
    assert store.forget(first["id"])
    assert store.search("", limit=10) == [second]
    assert not store.forget(first["id"])
    assert (tmp_path / ".mini-agent" / "memory.json").exists()


def test_rejects_secrets_and_oversized_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-test-value")
    store = MemoryStore(tmp_path)
    for text in (
        "sk-1234567890abcdef",
        "-----BEGIN PRIVATE KEY-----",
        "private-test-value",
        "x" * 1001,
        "   ",
    ):
        with pytest.raises(ValueError):
            store.remember(text)
    assert not (tmp_path / ".mini-agent").exists()


def test_invalid_and_duplicate_disk_records_are_refused(tmp_path: Path) -> None:
    state = tmp_path / ".mini-agent"
    state.mkdir()
    record = {
        "id": "a" * 32,
        "text": "saved",
        "source": "user",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (state / "memory.json").write_text(
        json.dumps({"version": 1, "records": [record, record]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="duplicate"):
        MemoryStore(tmp_path).search()


def test_workspaces_are_isolated(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    MemoryStore(first).remember("only first")

    assert MemoryStore(second).search() == []


def test_symlink_state_is_rejected_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / ".mini-agent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable in this environment")

    with pytest.raises(PermissionError):
        MemoryStore(tmp_path).search()


def test_regular_file_tools_cannot_access_memory_state(tmp_path: Path) -> None:
    state = tmp_path / ".mini-agent"
    state.mkdir()
    (state / "memory.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PermissionError, match="protected"):
        ReadFileTool(tmp_path).execute({"path": ".mini-agent/memory.json"})
    with pytest.raises(PermissionError, match="protected"):
        WriteFileTool(tmp_path).execute({"path": ".mini-agent/new.json", "content": "{}"})


def test_memory_record_limit_preserves_existing_records(tmp_path: Path) -> None:
    state = tmp_path / ".mini-agent"
    state.mkdir()
    records = [
        {
            "id": f"{index:032x}",
            "text": f"record {index}",
            "source": "user",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        for index in range(100)
    ]
    memory_path = state / "memory.json"
    memory_path.write_text(json.dumps({"version": 1, "records": records}), encoding="utf-8")

    with pytest.raises(ValueError, match="limited"):
        MemoryStore(tmp_path).remember("record 101")

    assert MemoryStore(tmp_path).search("", limit=100) == list(reversed(records))
    assert json.loads(memory_path.read_text(encoding="utf-8"))["records"] == records


def test_failed_atomic_replace_keeps_existing_file_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore(tmp_path)
    store.remember("original")
    memory_path = tmp_path / ".mini-agent" / "memory.json"
    original = memory_path.read_bytes()

    def fail_replace(*_args: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(memory_module.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="cannot be written"):
        store.remember("new record")

    assert memory_path.read_bytes() == original
    assert list(memory_path.parent.glob(".memory-*.tmp")) == []
