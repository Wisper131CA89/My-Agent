from pathlib import Path

import pytest

from mini_agent.tools.filesystem import ApplyPatchTool, ReadFileTool, WriteFileTool


def test_write_read_and_patch(tmp_path: Path) -> None:
    writer = WriteFileTool(tmp_path)
    reader = ReadFileTool(tmp_path)
    patcher = ApplyPatchTool(tmp_path)

    result = writer.execute({"path": "app.py", "content": "value = 1\n"})
    assert result.success
    assert "value = 1" in reader.execute({"path": "app.py"}).content

    patched = patcher.execute(
        {"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"}
    )
    assert patched.success
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "value = 2\n"


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

