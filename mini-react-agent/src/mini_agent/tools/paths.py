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
    return any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in SENSITIVE_PATTERNS)


def resolve_workspace_path(
    workspace: Path,
    requested: str,
    *,
    must_exist: bool,
    allow_sensitive: bool = False,
) -> Path:
    if not isinstance(requested, str) or not requested.strip():
        raise ValueError("path must be a non-empty string")

    raw = Path(requested)
    candidate = raw if raw.is_absolute() else workspace / raw

    if must_exist:
        resolved = candidate.resolve(strict=True)
    else:
        parent = candidate.parent.resolve(strict=True)
        resolved = parent / candidate.name

    if resolved != workspace and workspace not in resolved.parents:
        raise PermissionError("requested path is outside the workspace")
    if not allow_sensitive and is_sensitive(resolved):
        raise PermissionError("access to secret-like files is refused")
    return resolved


def relative_display(path: Path, workspace: Path) -> str:
    return "." if path == workspace else path.relative_to(workspace).as_posix()

