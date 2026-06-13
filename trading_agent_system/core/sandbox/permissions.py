from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class Permission(str, Enum):
    READ_MARKET = "read_market"
    READ_NEWS = "read_news"
    READ_ANNOUNCEMENTS = "read_announcements"
    READ_KNOWLEDGE = "read_knowledge"
    CALL_LLM = "call_llm"
    WRITE_STATE = "write_state"
    ANALYZE = "analyze"
    SEND_ALERT = "send_alert"
    SEND_NOTIFICATION = "send_notification"


@dataclass(frozen=True)
class PermissionProfile:
    role: str
    permissions: frozenset[Permission]
    agent: str | None = None
    max_tool_calls: int | None = None
    spent_tool_calls: int = 0

    @classmethod
    def reader(
        cls,
        agent: str | None = None,
        *,
        max_tool_calls: int | None = None,
    ) -> "PermissionProfile":
        return cls(
            role="reader",
            agent=agent,
            max_tool_calls=max_tool_calls,
            permissions=frozenset(
                {
                    Permission.READ_MARKET,
                    Permission.READ_NEWS,
                    Permission.READ_ANNOUNCEMENTS,
                    Permission.READ_KNOWLEDGE,
                }
            ),
        )

    @classmethod
    def analyst(
        cls,
        agent: str | None = None,
        *,
        max_tool_calls: int | None = None,
    ) -> "PermissionProfile":
        return cls(
            role="analyst",
            agent=agent,
            max_tool_calls=max_tool_calls,
            permissions=frozenset(
                {
                    Permission.READ_MARKET,
                    Permission.READ_NEWS,
                    Permission.READ_ANNOUNCEMENTS,
                    Permission.READ_KNOWLEDGE,
                    Permission.CALL_LLM,
                    Permission.ANALYZE,
                }
            ),
        )

    @classmethod
    def state_writer(
        cls,
        agent: str | None = None,
        *,
        max_tool_calls: int | None = None,
    ) -> "PermissionProfile":
        return cls(
            role="state_writer",
            agent=agent,
            max_tool_calls=max_tool_calls,
            permissions=frozenset(
                {
                    Permission.READ_MARKET,
                    Permission.READ_NEWS,
                    Permission.READ_ANNOUNCEMENTS,
                    Permission.READ_KNOWLEDGE,
                    Permission.CALL_LLM,
                    Permission.WRITE_STATE,
                }
            ),
        )

    @classmethod
    def notifier(
        cls,
        agent: str | None = None,
        *,
        max_tool_calls: int | None = None,
    ) -> "PermissionProfile":
        return cls(
            role="notifier",
            agent=agent,
            max_tool_calls=max_tool_calls,
            permissions=frozenset(
                {
                    Permission.READ_MARKET,
                    Permission.READ_NEWS,
                    Permission.READ_ANNOUNCEMENTS,
                    Permission.READ_KNOWLEDGE,
                    Permission.CALL_LLM,
                    Permission.SEND_ALERT,
                    Permission.SEND_NOTIFICATION,
                }
            ),
        )

    def allows_all(self, required_permissions: Iterable[Permission]) -> bool:
        return set(required_permissions).issubset(self.permissions)

    def can_call_tool(self) -> bool:
        return self.max_tool_calls is None or self.spent_tool_calls < self.max_tool_calls

    def record_tool_call(self) -> "PermissionProfile":
        return PermissionProfile(
            role=self.role,
            agent=self.agent,
            permissions=self.permissions,
            max_tool_calls=self.max_tool_calls,
            spent_tool_calls=self.spent_tool_calls + 1,
        )
