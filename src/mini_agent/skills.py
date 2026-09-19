"""Stable, transport-neutral descriptions for agent skills.

``timeout_seconds`` is declarative metadata.  A registry cannot safely stop an
arbitrary in-process Python callable, so a process/RPC transport that invokes a
skill is responsible for enforcing this limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SkillPermission = Literal["read", "edit", "run"]


@dataclass(frozen=True)
class SkillSpec:
    """A serializable capability contract advertised by a :class:`Tool`.

    The registry validates every field before accepting a tool.  ``examples``
    deliberately remains a list because callers commonly serialize it directly
    into a tool catalogue; callers should treat a registered specification as
    read-only metadata.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    returns: str
    permission: SkillPermission = "read"
    timeout_seconds: float = 30
    version: str = "1.0"
    examples: list[dict[str, Any]] = field(default_factory=list)
    source: str = "builtin"
