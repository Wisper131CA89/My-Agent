from __future__ import annotations

import json
import re
from collections.abc import Iterable
from copy import deepcopy
from math import isfinite
from typing import Any

from jsonschema import Draft202012Validator

from ..models import ToolResult
from ..skills import SkillSpec
from .base import Tool

_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PERMISSIONS = {"read", "edit", "run"}
_MODES = {"read", "edit", "run"}
_MODE_PERMISSIONS = {
    "read": {"read"},
    "edit": {"read", "edit"},
    "run": {"read", "edit", "run"},
}
_MAX_TIMEOUT_SECONDS = 3_600
_MAX_SCHEMA_CHARS = 64_000
_MAX_SCHEMA_DEPTH = 32
_MAX_SCHEMA_NODES = 2_000
_MAX_ARGUMENT_CHARS = 64_000
_MAX_ARGUMENT_DEPTH = 32
_MAX_ARGUMENT_NODES = 2_000
_VALID_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ToolRegistry:
    """Expose and execute tools permitted by legacy names and skill mode.

    Timeouts in :class:`SkillSpec` describe the capability contract.  This
    registry intentionally does not attempt to interrupt arbitrary in-process
    Python tools; transports/process runners must enforce them safely.
    """

    def __init__(
        self,
        tools: Iterable[Tool],
        max_output_chars: int = 20_000,
        allowed_tools: Iterable[str] | None = None,
        mode: str | None = None,
    ) -> None:
        if mode is not None and mode not in _MODES:
            raise ValueError("mode must be one of: read, edit, run")
        if not isinstance(max_output_chars, int) or max_output_chars < 0:
            raise ValueError("max_output_chars must be a non-negative integer")
        self._registered: dict[str, Tool] = {}
        self._specs: dict[str, SkillSpec] = {}
        self.max_output_chars = max_output_chars
        self.mode = mode
        self._legacy_allowed = set(allowed_tools) if allowed_tools is not None else None
        for tool in tools:
            self.register(tool)

    @staticmethod
    def _validate_finite_json(
        value: object,
        *,
        label: str,
        max_chars: int,
        max_depth: int,
        max_nodes: int,
    ) -> None:
        """Reject Python-only, non-finite, or excessively large JSON values."""
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must contain finite JSON values only") from exc
        if len(encoded) > max_chars:
            raise ValueError(f"{label} exceed the {max_chars} character limit")

        nodes = 0

        def inspect(value: object, depth: int = 0) -> None:
            nonlocal nodes
            nodes += 1
            if depth > max_depth or nodes > max_nodes:
                raise ValueError(f"{label} are too deeply nested or complex")
            if isinstance(value, dict):
                if not all(isinstance(key, str) for key in value):
                    raise ValueError(f"{label} must use string object keys")
                for child in value.values():
                    inspect(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    inspect(child, depth + 1)
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"{label} must contain JSON values only")

        inspect(value)

    @staticmethod
    def _validate_spec(spec: SkillSpec) -> None:
        if not isinstance(spec.name, str) or not _VALID_NAME.fullmatch(spec.name):
            raise ValueError("skill name must be 1-64 ASCII letters, digits, '_' or '-'")
        if not isinstance(spec.description, str) or not spec.description.strip():
            raise ValueError("skill description must be a non-empty string")
        if not isinstance(spec.returns, str) or not spec.returns.strip():
            raise ValueError("skill returns must be a non-empty string")
        if spec.permission not in _PERMISSIONS:
            raise ValueError("skill permission must be one of: read, edit, run")
        if (
            not isinstance(spec.timeout_seconds, (int, float))
            or isinstance(spec.timeout_seconds, bool)
            or not isfinite(spec.timeout_seconds)
            or not 0 < spec.timeout_seconds <= _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"skill timeout_seconds must be greater than 0 and at most {_MAX_TIMEOUT_SECONDS}"
            )
        if not isinstance(spec.version, str) or not spec.version.strip() or len(spec.version) > 64:
            raise ValueError("skill version must be a non-empty string of at most 64 characters")
        if not isinstance(spec.source, str) or not spec.source.strip() or len(spec.source) > 128:
            raise ValueError("skill source must be a non-empty string of at most 128 characters")
        if not isinstance(spec.examples, list) or not all(
            isinstance(example, dict) for example in spec.examples
        ):
            raise ValueError("skill examples must be a list of objects")
        if not isinstance(spec.parameters, dict):
            raise TypeError("skill parameters must be a JSON Schema object")
        ToolRegistry._validate_finite_json(
            spec.parameters,
            label="skill parameters",
            max_chars=_MAX_SCHEMA_CHARS,
            max_depth=_MAX_SCHEMA_DEPTH,
            max_nodes=_MAX_SCHEMA_NODES,
        )
        ToolRegistry._validate_finite_json(
            spec.examples,
            label="skill examples",
            max_chars=_MAX_SCHEMA_CHARS,
            max_depth=_MAX_SCHEMA_DEPTH,
            max_nodes=_MAX_SCHEMA_NODES,
        )

        def inspect_schema(value: object, depth: int = 0) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"$ref", "$dynamicRef"} and (
                        not isinstance(child, str) or not child.startswith("#/$defs/")
                    ):
                        raise ValueError("skill parameters may only use local #/$defs/ references")
                    inspect_schema(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    inspect_schema(child, depth + 1)

        inspect_schema(spec.parameters)
        try:
            Draft202012Validator.check_schema(spec.parameters)
        except Exception as exc:  # jsonschema exposes several validation exception types.
            raise ValueError("skill parameters must be a valid JSON Schema") from exc

    def _is_permitted(self, spec: SkillSpec) -> bool:
        if self._legacy_allowed is not None and spec.name not in self._legacy_allowed:
            return False
        return self.mode is None or spec.permission in _MODE_PERMISSIONS[self.mode]

    def register(self, tool: Tool) -> None:
        """Validate and add a tool; duplicate capability names are rejected."""
        if not isinstance(tool, Tool):
            raise TypeError("registered skills must be Tool instances")
        spec = tool.skill_spec()
        if not isinstance(spec, SkillSpec):
            raise TypeError("Tool.skill_spec() must return SkillSpec")
        self._validate_spec(spec)
        if spec.name != tool.name:
            raise ValueError("Tool.skill_spec().name must match Tool.name")
        if spec.name in self._registered:
            raise ValueError(f"duplicate skill name: {spec.name}")
        # A frozen dataclass does not freeze its nested dict/list fields.  Keep
        # a deep snapshot so a tool (or a catalogue caller) cannot mutate its
        # advertised schema after policy validation.
        snapshot = deepcopy(spec)
        self._registered[snapshot.name] = tool
        self._specs[snapshot.name] = snapshot
        self._refresh_permitted()

    def _refresh_permitted(self) -> None:
        self._tools = {
            name: tool
            for name, tool in self._registered.items()
            if self._is_permitted(self._specs[name])
        }
        # Kept for backwards compatibility with agent/UI integrations.
        self._allowed = set(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": deepcopy(spec.parameters),
                },
            }
            for name in self._tools
            for spec in (self._specs[name],)
        ]

    def skill_specs(self) -> list[SkillSpec]:
        """Return the permitted skill contracts in registration order."""
        return [deepcopy(self._specs[name]) for name in self._tools]

    def descriptors(self) -> list[SkillSpec]:
        """Compatibility-friendly alias for skill catalogue consumers."""
        return self.skill_specs()

    def skills(self) -> list[SkillSpec]:
        """Short alias for :meth:`skill_specs`."""
        return self.skill_specs()

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if not isinstance(name, str) or name not in self._allowed:
            return ToolResult(
                False, "This tool is not permitted in the selected mode.", "tool_not_permitted"
            )
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool: {name}", "unknown_tool")
        if not isinstance(arguments, dict) or "_invalid_json" in arguments:
            return ToolResult(
                False, "Tool arguments must be a valid JSON object.", "invalid_arguments"
            )
        try:
            self._validate_finite_json(
                arguments,
                label="tool arguments",
                max_chars=_MAX_ARGUMENT_CHARS,
                max_depth=_MAX_ARGUMENT_DEPTH,
                max_nodes=_MAX_ARGUMENT_NODES,
            )
        except ValueError:
            return ToolResult(
                False, "Tool arguments must be a finite, bounded JSON object.", "invalid_arguments"
            )
        try:
            error = next(
                iter(Draft202012Validator(self._specs[name].parameters).iter_errors(arguments)),
                None,
            )
        except Exception:  # noqa: BLE001 - invalid/cyclic schemas must not break the protocol.
            return ToolResult(
                False, "Tool arguments could not be safely validated.", "invalid_arguments"
            )
        if error:
            # Do not echo model supplied values: schema libraries can include them in messages.
            return ToolResult(
                False, "Tool arguments do not match the required schema.", "invalid_arguments"
            )
        try:
            result = tool.execute(arguments)
        except FileNotFoundError:
            result = ToolResult(False, "Requested file was not found.", "file_not_found")
        except (PermissionError, ValueError, FileExistsError) as exc:
            # Only our known built-ins may return their carefully reviewed
            # rejection text.  A plugin/custom tool exception can include a
            # private path, argument, token, or remote service response.
            if self._is_trusted_builtin(name):
                result = ToolResult(False, str(exc), "tool_rejected")
            else:
                result = ToolResult(False, "Tool rejected the request.", "tool_rejected")
        except Exception:  # noqa: BLE001 - tools are third-party/untrusted execution boundaries.
            # Arbitrary exception details can contain private paths or secrets.
            result = ToolResult(
                False, "Tool execution failed unexpectedly.", "tool_execution_failed", True
            )
        result = self._sanitize_result(result)
        return ToolResult(
            result.success,
            result.content[: self.max_output_chars],
            result.error_code,
            result.retryable,
        )

    @staticmethod
    def _sanitize_result(result: object) -> ToolResult:
        """Keep untrusted tool return values safe for event and model metadata."""
        if (
            not isinstance(result, ToolResult)
            or not isinstance(result.success, bool)
            or not isinstance(result.content, str)
            or (
                result.error_code is not None
                and (
                    not isinstance(result.error_code, str)
                    or not _VALID_ERROR_CODE.fullmatch(result.error_code)
                )
            )
            or (result.retryable is not None and not isinstance(result.retryable, bool))
        ):
            return ToolResult(
                False, "Tool execution returned an invalid result.", "tool_execution_failed", True
            )
        return ToolResult(result.success, result.content, result.error_code, result.retryable)

    def _is_trusted_builtin(self, name: str) -> bool:
        # ``source`` is declarative metadata supplied by a tool, not an
        # authority grant.  Trust exception text only for the six shipped
        # implementations, not an external subclass which reuses a name.
        return (
            self._specs[name].source == "builtin"
            and self._registered[name].__class__.__module__.startswith("mini_agent.tools.")
            and name
            in {
                "list_files",
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "run_command",
            }
        )

    @staticmethod
    def message_content(result: ToolResult) -> str:
        result = ToolRegistry._sanitize_result(result)
        return json.dumps(
            {
                "success": result.success,
                "content": result.content,
                "error_code": result.error_code,
                "retryable": result.retryable,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
