from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trading_agent_system.core.sandbox import Permission

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    handler: ToolHandler
    required_permissions: frozenset[Permission] | set[Permission] = field(
        default_factory=frozenset
    )
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = 30.0
    retries: int = 0
    rate_limit_per_minute: int | None = None
    cacheable: bool = False
    fallback: ToolHandler | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_permissions",
            frozenset(self.required_permissions),
        )
