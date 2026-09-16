"""Central, deliberately conservative policy for workspace paths."""

from __future__ import annotations

import fnmatch
from pathlib import Path

IGNORED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
SENSITIVE_PATTERNS = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.toml",
}


def is_sensitive(path: Path) -> bool:
    """Return whether this *name* is secret-like (case-insensitively)."""
    return any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in SENSITIVE_PATTERNS)


def is_protected(path: Path) -> bool:
    return path.name.lower() in IGNORED_NAMES


def _is_link(path: Path) -> bool:
    """Identify symlinks and Windows directory junctions without following them."""
    try:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    except OSError:
        return True


def _parts_under_workspace(workspace: Path, requested: str) -> tuple[Path, tuple[str, ...]]:
    if not isinstance(requested, str) or not requested.strip():
        raise ValueError("path must be a non-empty string")
    raw = Path(requested)
    if any(part == ".." for part in raw.parts):
        raise PermissionError("requested path is outside the workspace")
    candidate = raw if raw.is_absolute() else workspace / raw
    try:
        parts = candidate.relative_to(workspace).parts
    except ValueError as exc:
        raise PermissionError("requested path is outside the workspace") from exc
    return candidate, parts


def _check_names(parts: tuple[str, ...], *, allow_sensitive: bool) -> None:
    for part in parts:
        # Windows accepts alternate data streams and normalizes trailing dots /
        # spaces. Reject both spellings so policy cannot be bypassed as
        # ``.env.:stream`` or ``.env ``. Device names are never useful files.
        normalized = part.rstrip(". ")
        device = normalized.upper().split(".", 1)[0]
        if (
            not normalized
            or normalized != part
            or ":" in part
            or device
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                "COM1",
                "COM2",
                "COM3",
                "COM4",
                "COM5",
                "COM6",
                "COM7",
                "COM8",
                "COM9",
                "LPT1",
                "LPT2",
                "LPT3",
                "LPT4",
                "LPT5",
                "LPT6",
                "LPT7",
                "LPT8",
                "LPT9",
            }
        ):
            raise PermissionError("requested path contains an unsafe Windows name")
        name = Path(part)
        if not allow_sensitive and is_sensitive(name):
            raise PermissionError("access to secret-like files is refused")
        if is_protected(name):
            raise PermissionError("access to protected directories is refused")


def resolve_workspace_path(
    workspace: Path, requested: str, *, must_exist: bool, allow_sensitive: bool = False
) -> Path:
    """Validate a target without following links or permitting alias-based escapes.

    Missing leaf and parent components are allowed for file creation, but the
    nearest existing ancestor is checked first. This makes nested creation
    possible while retaining the policy used by read, list, and search.
    """
    root = workspace.resolve(strict=True)
    candidate, parts = _parts_under_workspace(root, requested)
    _check_names(parts, allow_sensitive=allow_sensitive)
    current = root
    for part in parts:
        current = current / part
        if not current.exists() and not current.is_symlink():
            break
        if _is_link(current):
            raise PermissionError(
                "requested path uses a link and may resolve outside the workspace"
            )
        try:
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise PermissionError("requested path cannot be resolved safely") from exc
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PermissionError("requested path is outside the workspace") from exc
        _check_names(resolved.relative_to(root).parts, allow_sensitive=allow_sensitive)
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"path does not exist: {requested}")
    if must_exist and _is_link(candidate):
        raise PermissionError("requested path uses a link and may resolve outside the workspace")
    return candidate


def relative_display(path: Path, workspace: Path) -> str:
    return "." if path == workspace else path.relative_to(workspace).as_posix()
