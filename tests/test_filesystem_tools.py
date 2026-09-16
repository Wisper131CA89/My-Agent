from pathlib import Path

import pytest

from mini_agent.tools.filesystem import ApplyPatchTool, ListFilesTool, ReadFileTool, WriteFileTool


def test_write_read_and_patch(tmp_path: Path) -> None:
    writer = WriteFileTool(tmp_path)
    reader = ReadFileTool(tmp_path)
    patcher = ApplyPatchTool(tmp_path)

    result = writer.execute({"path": "app.py", "content": "value = 1\n"})
    assert result.success
    assert "value = 1" in reader.execute({"path": "app.py"}).content

    patched = patcher.execute({"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"})
    assert patched.success
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    assert "exact replacement" in patched.content


def test_write_refuses_accidental_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        WriteFileTool(tmp_path).execute({"path": "app.py", "content": "replacement"})
    assert path.read_text(encoding="utf-8") == "original"


def test_patch_requires_unique_match(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("same\nsame\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly once"):
        ApplyPatchTool(tmp_path).execute(
            {"path": "app.py", "old_text": "same", "new_text": "different"}
        )


def test_write_creates_nested_directories(tmp_path: Path) -> None:
    result = WriteFileTool(tmp_path).execute({"path": "nested/deep/app.py", "content": "ok"})
    assert result.success
    assert (tmp_path / "nested/deep/app.py").read_text(encoding="utf-8") == "ok"


def test_read_refuses_oversized_file(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("x" * 1_000_001, encoding="utf-8")
    with pytest.raises(ValueError, match="read limit"):
        ReadFileTool(tmp_path).execute({"path": "large.txt"})


def test_list_honors_depth_limit(tmp_path: Path) -> None:
    (tmp_path / "top.txt").write_text("top", encoding="utf-8")
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("deep", encoding="utf-8")
    result = ListFilesTool(tmp_path).execute({"max_depth": 1})
    assert "top.txt" in result.content
    assert "one/two/deep.txt" not in result.content
