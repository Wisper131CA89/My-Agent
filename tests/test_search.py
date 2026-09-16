from pathlib import Path

import pytest

from mini_agent.tools.search import SearchTextTool


def test_search_finds_literal_text_and_respects_pattern(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("needle = 1\n", encoding="utf-8")
    (tmp_path / "two.txt").write_text("needle = 2\n", encoding="utf-8")
    result = SearchTextTool(tmp_path).execute({"query": "needle", "file_pattern": "*.py"})
    assert result.success
    assert "one.py:1:needle" in result.content
    assert "two.txt" not in result.content


def test_search_skips_sensitive_and_protected_tree(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("needle=secret", encoding="utf-8")
    protected = tmp_path / ".git"
    protected.mkdir()
    (protected / "config").write_text("needle=hidden", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("needle=shown", encoding="utf-8")
    result = SearchTextTool(tmp_path).execute({"query": "needle"})
    assert "visible.txt" in result.content
    assert ".env" not in result.content
    assert ".git" not in result.content


def test_search_refuses_direct_sensitive_target(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("needle", encoding="utf-8")
    with pytest.raises(PermissionError, match="secret-like"):
        SearchTextTool(tmp_path).execute({"query": "needle", "path": ".env"})


def test_search_output_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_text("needle\n" * 250, encoding="utf-8")
    result = SearchTextTool(tmp_path).execute({"query": "needle"})
    assert "output truncated" in result.content
    assert len(result.content.splitlines()) == 201


def test_search_skips_binary_file(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"needle\x00hidden")
    assert SearchTextTool(tmp_path).execute({"query": "needle"}).content == "No matches found"
