"""Persistent, deliberately small, trusted command recipes.

Recipes are convenience records, not an operating-system security boundary.
Verification means that the currently permitted commands completed once; it does
not establish that their result is semantically correct.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .models import ToolResult
from .tools.paths import IGNORED_NAMES, _is_link, is_sensitive
from .tools.registry import ToolRegistry

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_TOOLS = frozenset({"read_file", "list_files", "search_text", "run_command"})
_MAX_RECIPES = 30
_MAX_STEPS = 8
_MAX_STATE_BYTES = 1_000_000
_MAX_FINGERPRINT_FILES = 1_000
_MAX_FINGERPRINT_BYTES = 2_000_000
_SKIP_FINGERPRINT = frozenset(set(IGNORED_NAMES) | {".mini-agent", "caches"})
_MAX_FINGERPRINT_DEPTH = 32
_MAX_FINGERPRINT_NODES = 5_000


class RecipeManager:
    """Store and replay explicitly verified, workspace-local check sequences."""

    def __init__(self, workspace: Path, registry: ToolRegistry, writable: bool = True) -> None:
        self.workspace = Path(workspace).resolve(strict=True)
        if _is_link(self.workspace):
            raise PermissionError("workspace must not be a link")
        self.registry = registry
        self.writable = writable
        self._recipes = self._load()

    def create(self, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        self._require_writable()
        self._validate_recipe(name, steps)
        if name in self._recipes:
            raise ValueError("recipe already exists; overwriting recipes is refused")
        if len(self._recipes) >= _MAX_RECIPES:
            raise ValueError("recipe storage holds at most 30 recipes")
        recipe = {"name": name, "steps": deepcopy(steps), "verified": False, "fingerprint": None}
        self._recipes[name] = recipe
        try:
            self._save()
        except BaseException:
            del self._recipes[name]
            raise
        return self._public(recipe)

    def list(self) -> list[dict[str, Any]]:
        return [self._public(self._recipes[name]) for name in sorted(self._recipes)]

    def forget(self, name: str) -> bool:
        if not isinstance(name, str) or name not in self._recipes:
            return False
        self._require_writable()
        saved = self._recipes.pop(name)
        try:
            self._save()
        except BaseException:
            self._recipes[name] = saved
            raise
        return True

    def verify(self, name: str) -> ToolResult:
        recipe = self._recipes.get(name)
        if recipe is None:
            return ToolResult(False, "Recipe was not found.", "recipe_not_found")
        if not self.writable:
            return ToolResult(
                False, "Verifying recipes requires writable run permission.", "tool_not_permitted"
            )
        issue = self._preflight(recipe["steps"])
        if issue is not None:
            return issue
        # Reverification never leaves a prior success usable after a failed
        # command, fingerprint problem, or interrupt.
        self._revoke(recipe)
        try:
            before = self._fingerprint(recipe["steps"])
        except (OSError, PermissionError, ValueError):
            return ToolResult(
                False,
                "Workspace fingerprint could not be checked; recipe was not verified.",
                "stale_recipe",
            )
        try:
            outcomes, failed = self._execute(recipe["steps"])
        except BaseException:
            self._revoke(recipe)
            raise
        if failed is not None:
            return failed
        # Every recipe must actually exercise a successful command, rather
        # than merely containing one alongside read-only steps.
        if not any(step["tool"] == "run_command" and success for step, success in outcomes):
            return ToolResult(
                False, "Recipe did not complete a command successfully.", "not_verified"
            )
        try:
            after = self._fingerprint(recipe["steps"])
        except (OSError, PermissionError, ValueError):
            return ToolResult(
                False,
                "Workspace fingerprint could not be checked; recipe was not verified.",
                "stale_recipe",
            )
        if before != after:
            return ToolResult(
                False, "Workspace changed during verification; reverify first.", "stale_recipe"
            )
        recipe["verified"] = True
        recipe["fingerprint"] = after
        try:
            self._save()
        except BaseException:
            recipe["verified"] = False
            recipe["fingerprint"] = None
            raise
        return ToolResult(True, self._bounded_status(outcomes))

    def run(self, name: str) -> ToolResult:
        recipe = self._recipes.get(name)
        if recipe is None:
            return ToolResult(False, "Recipe was not found.", "recipe_not_found")
        # A read-only manager must never begin a stored command, even if a
        # previous writable manager persisted a verified record.
        if not self.writable or getattr(self.registry, "mode", None) in {"read", "edit"}:
            return ToolResult(
                False, "Running recipes requires run permission.", "tool_not_permitted"
            )
        if not recipe["verified"]:
            return ToolResult(False, "Recipe must be verified before it can run.", "not_verified")
        try:
            current = self._fingerprint(recipe["steps"])
        except (OSError, PermissionError, ValueError):
            self._revoke(recipe)
            return ToolResult(
                False, "Workspace fingerprint could not be checked; reverify first.", "stale_recipe"
            )
        if current != recipe["fingerprint"]:
            self._revoke(recipe)
            return ToolResult(
                False, "Workspace changed; reverify this recipe first.", "stale_recipe"
            )
        issue = self._preflight(recipe["steps"])
        if issue is not None:
            return issue
        try:
            outcomes, failed = self._execute(recipe["steps"])
        except BaseException:
            self._revoke(recipe)
            raise
        if failed is not None:
            self._revoke(recipe)
            return failed
        return ToolResult(True, self._bounded_status(outcomes))

    def _execute(
        self, steps: list[dict[str, Any]]
    ) -> tuple[list[tuple[dict[str, Any], bool]], ToolResult | None]:
        outcomes: list[tuple[dict[str, Any], bool]] = []
        for step in steps:
            result = self.registry.execute(step["tool"], deepcopy(step["arguments"]))
            outcomes.append((step, result.success))
            if not result.success:
                return outcomes, ToolResult(
                    False,
                    self._bounded_status(outcomes),
                    result.error_code or "recipe_step_failed",
                    result.retryable,
                )
        return outcomes, None

    def _preflight(self, steps: list[dict[str, Any]]) -> ToolResult | None:
        schemas = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in self.registry.schemas()
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
        for step in steps:
            tool = step["tool"]
            schema = schemas.get(tool)
            if schema is None:
                return ToolResult(
                    False, "Recipe tool is not permitted currently.", "tool_not_permitted"
                )
            try:
                invalid = next(
                    iter(Draft202012Validator(schema).iter_errors(step["arguments"])), None
                )
            except Exception:  # noqa: BLE001 - a changed registry schema must fail closed.
                return ToolResult(
                    False, "Recipe arguments are no longer valid.", "invalid_arguments"
                )
            if invalid is not None:
                return ToolResult(
                    False, "Recipe arguments are no longer valid.", "invalid_arguments"
                )
        if any(step["tool"] == "run_command" for step in steps) and getattr(
            self.registry, "mode", None
        ) in {"read", "edit"}:
            return ToolResult(
                False, "Recipe commands require run permission.", "tool_not_permitted"
            )
        return None

    @staticmethod
    def _bounded_status(outcomes: list[tuple[dict[str, Any], bool]]) -> str:
        # Do not retain or return tool output: a recipe result is status-only.
        labels = [f"{step['tool']}:{'ok' if success else 'failed'}" for step, success in outcomes]
        return "Recipe steps: " + ", ".join(labels[:_MAX_STEPS])

    def _revoke(self, recipe: dict[str, Any]) -> None:
        recipe["verified"] = False
        recipe["fingerprint"] = None
        if self.writable:
            self._save()

    def _fingerprint(self, steps: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        digest.update(json.dumps(steps, sort_keys=True, separators=(",", ":")).encode())
        files = 0
        total = 0

        nodes = 0

        def walk(directory: Path, depth: int = 0) -> None:
            nonlocal files, total, nodes
            if depth > _MAX_FINGERPRINT_DEPTH:
                raise ValueError("workspace is too deeply nested to fingerprint")
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda value: value.name):
                    nodes += 1
                    if nodes > _MAX_FINGERPRINT_NODES:
                        raise ValueError("workspace has too many entries to fingerprint")
                    if entry.name in _SKIP_FINGERPRINT or is_sensitive(Path(entry.name)):
                        continue
                    path = Path(entry.path)
                    if _is_link(path):
                        raise PermissionError("workspace contains an unsafe link")
                    if entry.is_dir(follow_symlinks=False):
                        walk(path, depth + 1)
                    elif entry.is_file(follow_symlinks=False):
                        files += 1
                        if files > _MAX_FINGERPRINT_FILES:
                            raise ValueError("workspace has too many files to fingerprint")
                        size = entry.stat(follow_symlinks=False).st_size
                        total += size
                        if total > _MAX_FINGERPRINT_BYTES:
                            raise ValueError("workspace is too large to fingerprint")
                        digest.update(path.relative_to(self.workspace).as_posix().encode())
                        digest.update(b"\0")
                        with path.open("rb") as source:
                            read = 0
                            while chunk := source.read(65_536):
                                read += len(chunk)
                                if read > size:
                                    raise ValueError("workspace file changed while fingerprinting")
                                digest.update(chunk)

        walk(self.workspace)
        return digest.hexdigest()

    def _state_path(self) -> Path:
        return self.workspace / ".mini-agent" / "recipes.json"

    def _safe_state_parent(self, *, create: bool) -> Path:
        if _is_link(self.workspace):
            raise PermissionError("workspace must not be a link")
        parent = self.workspace / ".mini-agent"
        if _is_link(parent):
            raise PermissionError("recipe state directory must not be a link")
        if create and not parent.exists():
            parent.mkdir(mode=0o700)
        if parent.exists() and (not parent.is_dir() or _is_link(parent)):
            raise PermissionError("recipe state directory is unsafe")
        return parent

    def _load(self) -> dict[str, dict[str, Any]]:
        state = self._state_path()
        parent = self._safe_state_parent(create=False)
        if _is_link(state):
            raise ValueError("recipe state is unsafe or too large")
        if not parent.exists() or not state.exists():
            return {}
        if _is_link(state) or not state.is_file() or state.stat().st_size > _MAX_STATE_BYTES:
            raise ValueError("recipe state is unsafe or too large")
        try:
            with state.open("rb") as source:
                data = source.read(_MAX_STATE_BYTES + 1)
            if len(data) > _MAX_STATE_BYTES:
                raise ValueError("recipe state is unsafe or too large")
            raw = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("recipe state is invalid") from exc
        if (
            not isinstance(raw, dict)
            or raw.keys() != {"version", "recipes"}
            or type(raw["version"]) is not int
            or raw["version"] != 1
        ):
            raise ValueError("recipe state has an invalid schema")
        if not isinstance(raw["recipes"], list) or len(raw["recipes"]) > _MAX_RECIPES:
            raise ValueError("recipe state has an invalid schema")
        recipes: dict[str, dict[str, Any]] = {}
        for recipe in raw["recipes"]:
            if not isinstance(recipe, dict) or set(recipe) != {
                "name",
                "steps",
                "verified",
                "fingerprint",
            }:
                raise ValueError("recipe state has an invalid schema")
            self._validate_recipe(recipe["name"], recipe["steps"])
            if not isinstance(recipe["verified"], bool) or (
                recipe["fingerprint"] is not None
                and (
                    not isinstance(recipe["fingerprint"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", recipe["fingerprint"]) is None
                )
            ):
                raise ValueError("recipe state has an invalid schema")
            if (
                recipe["verified"] != (recipe["fingerprint"] is not None)
                or recipe["name"] in recipes
            ):
                raise ValueError("recipe state has an invalid schema")
            recipes[recipe["name"]] = deepcopy(recipe)
        return recipes

    def _save(self) -> None:
        parent = self._safe_state_parent(create=True)
        state = self._state_path()
        if _is_link(state):
            raise PermissionError("recipe state file must not be a link")
        payload = json.dumps(
            {"version": 1, "recipes": [self._recipes[name] for name in sorted(self._recipes)]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > _MAX_STATE_BYTES:
            raise ValueError("recipe state exceeds the size limit")
        descriptor, temporary = tempfile.mkstemp(prefix=".recipes-", dir=parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            if _is_link(parent) or (state.exists() and _is_link(state)):
                raise PermissionError("recipe state changed to a link")
            os.replace(temporary, state)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _validate_recipe(name: object, steps: object) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("recipe name must be lowercase ASCII and at most 32 characters")
        if not isinstance(steps, list) or not 1 <= len(steps) <= _MAX_STEPS:
            raise ValueError("recipe must contain between 1 and 8 steps")
        try:
            encoded = json.dumps(steps, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("recipe steps must be finite JSON") from exc
        if len(encoded) > 64_000:
            raise ValueError("recipe steps are too large")
        for step in steps:
            if not isinstance(step, dict) or set(step) != {"tool", "arguments"}:
                raise ValueError("recipe steps must contain only tool and arguments")
            if (
                not isinstance(step["tool"], str)
                or step["tool"] not in _TOOLS
                or not isinstance(step["arguments"], dict)
            ):
                raise ValueError("recipe has an unsupported tool or invalid arguments")

    def _require_writable(self) -> None:
        if not self.writable:
            raise PermissionError("recipe storage is read-only")

    @staticmethod
    def _public(recipe: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": recipe["name"],
            "steps": deepcopy(recipe["steps"]),
            "verified": recipe["verified"],
        }
