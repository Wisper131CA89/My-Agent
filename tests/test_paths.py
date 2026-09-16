from pathlib import Path

import pytest

from mini_agent.tools.paths import resolve_workspace_path


def test_path_inside_workspace_is_allowed(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("ok", encoding="utf-8")
    assert resolve_workspace_path(tmp_path, "file.txt", must_exist=True) == target


def test_parent_escape_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="outside"):
        resolve_workspace_path(tmp_path, "../secret.txt", must_exist=False)


@pytest.mark.parametrize("name", [".env", "private.pem", "id_rsa", "credentials.json"])
def test_secret_like_files_are_refused(tmp_path: Path, name: str) -> None:
    target = tmp_path / name
    target.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError, match="secret-like"):
        resolve_workspace_path(tmp_path, name, must_exist=True)


def test_symlink_escape_is_refused_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available for this user")
    with pytest.raises(PermissionError, match="outside"):
        resolve_workspace_path(tmp_path, "link.txt", must_exist=True)


@pytest.mark.parametrize("path", [".git/config", "node_modules/pkg/index.js", ".env/value"])
def test_protected_directories_are_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(PermissionError, match="protected|secret-like"):
        resolve_workspace_path(tmp_path, path, must_exist=False)


def test_nested_new_path_is_allowed(tmp_path: Path) -> None:
    assert (
        resolve_workspace_path(tmp_path, "new/deep/file.txt", must_exist=False)
        == tmp_path / "new/deep/file.txt"
    )


def test_link_inside_workspace_is_refused_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    link = tmp_path / "alias.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not available for this user")
    with pytest.raises(PermissionError, match="link"):
        resolve_workspace_path(tmp_path, "alias.txt", must_exist=True)


@pytest.mark.parametrize("name", [".env.", "credentials.json:stream", "NUL.txt"])
def test_windows_alias_spellings_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(PermissionError, match="unsafe Windows name"):
        resolve_workspace_path(tmp_path, name, must_exist=False)
