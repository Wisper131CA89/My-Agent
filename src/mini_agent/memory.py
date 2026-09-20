"""Explicit, workspace-local persistent memory for the mini agent.

Memory is deliberately opt-in: callers must explicitly pass text to
``remember``.  This module is not a general secret scanner, but rejects common
accidental API-key and PEM inputs before they reach the on-disk store.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_RECORDS = 100
_MAX_FILE_BYTES = 1_000_000
_MAX_TEXT_LENGTH = 1_000
_ALLOWED_SOURCES = {"user", "task"}
_API_KEY_ENV_MARKER = "API_KEY"
_SK_KEY = re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{8,}(?![\w-])")
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----")


class MemoryStore:
    """Persist a small, user-approved memory list below one workspace.

    The store never creates its state directory merely by being constructed or
    read.  Mutating operations create it only after link checks and use an
    atomic replacement, so an interrupted write leaves the prior JSON intact.
    """

    def __init__(self, workspace: Path, writable: bool = True) -> None:
        self.workspace = Path(workspace)
        self.writable = writable

    @property
    def state_dir(self) -> Path:
        return self.workspace / ".mini-agent"

    @property
    def path(self) -> Path:
        return self.state_dir / "memory.json"

    def remember(self, text: str, source: str = "user") -> dict[str, str]:
        """Save explicitly supplied text and return its immutable record."""
        self._require_writable()
        self._validate_new_record(text, source)
        records = self._load()
        if len(records) >= _MAX_RECORDS:
            raise ValueError(f"memory store is limited to {_MAX_RECORDS} records")
        record = {
            "id": uuid.uuid4().hex,
            "text": text,
            "source": source,
            "created_at": datetime.now(UTC).isoformat(),
        }
        records.append(record)
        self._write(records)
        return record.copy()

    def search(self, query: str = "", limit: int = 10) -> list[dict[str, str]]:
        """Return recent records matching a substring or all simple query terms."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []

        normalized = query.casefold().strip()
        terms = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", normalized)
        matches: list[dict[str, str]] = []
        for record in reversed(self._load()):
            body = record["text"].casefold()
            if (
                not normalized
                or normalized in body
                or (terms and all(term in body for term in terms))
            ):
                matches.append(record.copy())
                if len(matches) >= min(limit, _MAX_RECORDS):
                    break
        return matches

    def forget(self, record_id: str) -> bool:
        """Delete one record, never the state file or its directory."""
        self._require_writable()
        if not isinstance(record_id, str):
            raise TypeError("record_id must be a string")
        records = self._load()
        remaining = [record for record in records if record["id"] != record_id]
        if len(remaining) == len(records):
            return False
        self._write(remaining)
        return True

    def _require_writable(self) -> None:
        if not self.writable:
            raise PermissionError("memory store is read-only")

    def _validate_new_record(self, text: str, source: str) -> None:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            raise ValueError("memory text must not be blank")
        if len(text) > _MAX_TEXT_LENGTH:
            raise ValueError(f"memory text must be at most {_MAX_TEXT_LENGTH} characters")
        if not isinstance(source, str) or source not in _ALLOWED_SOURCES:
            raise ValueError("source must be 'user' or 'task'")
        if self._contains_secret(text):
            raise ValueError("refusing apparent secret; memory is not a secret store")

    @staticmethod
    def _contains_secret(text: str) -> bool:
        if _SK_KEY.search(text) or _PEM.search(text):
            return True
        return any(
            value and value in text
            for name, value in os.environ.items()
            if _API_KEY_ENV_MARKER in name.upper()
        )

    @staticmethod
    def _is_link(path: Path) -> bool:
        try:
            return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
        except OSError as exc:
            raise PermissionError("memory state path cannot be inspected safely") from exc

    def _check_state_paths(self) -> tuple[bool, bool]:
        """Check existing state components without resolving or following them."""
        try:
            if not self.workspace.is_dir():
                raise FileNotFoundError(f"workspace does not exist: {self.workspace}")
            if self._is_link(self.workspace):
                raise PermissionError("workspace link is not accepted for persistent memory")

            directory_exists = self.state_dir.exists() or self.state_dir.is_symlink()
            if directory_exists and (self._is_link(self.state_dir) or not self.state_dir.is_dir()):
                raise PermissionError("memory state directory must be a real directory")

            file_exists = self.path.exists() or self.path.is_symlink()
            if file_exists and (self._is_link(self.path) or not self.path.is_file()):
                raise PermissionError("memory state file must be a real regular file")
            return directory_exists, file_exists
        except OSError as exc:
            raise PermissionError("memory state path cannot be inspected safely") from exc

    def _load(self) -> list[dict[str, str]]:
        _, file_exists = self._check_state_paths()
        if not file_exists:
            return []
        try:
            if self.path.stat().st_size > _MAX_FILE_BYTES:
                raise ValueError("memory state file exceeds size limit")
            with self.path.open("rb") as stream:
                data = stream.read(_MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise PermissionError("memory state file cannot be read safely") from exc
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError("memory state file exceeds size limit")
        self._check_state_paths()
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("memory state file is not valid JSON") from exc
        return self._validate_payload(payload)

    def _validate_payload(self, payload: Any) -> list[dict[str, str]]:
        if not isinstance(payload, dict) or set(payload) != {"version", "records"}:
            raise ValueError("memory state file has an invalid structure")
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError("memory state file has an unsupported version")
        records = payload["records"]
        if not isinstance(records, list) or len(records) > _MAX_RECORDS:
            raise ValueError("memory state file has an invalid record list")
        seen: set[str] = set()
        validated: list[dict[str, str]] = []
        for record in records:
            if not isinstance(record, dict) or set(record) != {
                "id",
                "text",
                "source",
                "created_at",
            }:
                raise ValueError("memory state file contains an invalid record")
            record_id = record["id"]
            text = record["text"]
            source = record["source"]
            created_at = record["created_at"]
            if (
                not isinstance(record_id, str)
                or not isinstance(text, str)
                or not text.strip()
                or len(text) > _MAX_TEXT_LENGTH
                or not isinstance(source, str)
                or source not in _ALLOWED_SOURCES
                or not isinstance(created_at, str)
            ):
                raise ValueError("memory state file contains an invalid record")
            if self._contains_secret(text):
                raise ValueError("memory state file contains an apparent secret")
            try:
                valid_id = uuid.UUID(record_id).hex == record_id
            except ValueError:
                valid_id = False
            if not valid_id:
                raise ValueError("memory state file contains an invalid record")
            try:
                parsed_time = datetime.fromisoformat(created_at)
            except ValueError as exc:
                raise ValueError("memory state file contains an invalid timestamp") from exc
            if parsed_time.tzinfo is None or parsed_time.utcoffset() != UTC.utcoffset(None):
                raise ValueError("memory state file timestamp must be UTC")
            if record_id in seen:
                raise ValueError("memory state file contains duplicate record ids")
            seen.add(record_id)
            validated.append(record.copy())
        return validated

    def _write(self, records: list[dict[str, str]]) -> None:
        directory_exists, _ = self._check_state_paths()
        if not directory_exists:
            try:
                self.state_dir.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise PermissionError("memory state directory cannot be created") from exc
        self._check_state_paths()
        payload = json.dumps({"version": 1, "records": records}, ensure_ascii=False).encode("utf-8")
        if len(payload) > _MAX_FILE_BYTES:
            raise ValueError("memory state file exceeds size limit")

        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.state_dir, prefix=".memory-", suffix=".tmp", delete=False
            ) as temporary:
                temp_name = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            self._check_state_paths()
            os.replace(temp_name, self.path)
            temp_name = None
        except OSError as exc:
            raise PermissionError("memory state file cannot be written safely") from exc
        finally:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
