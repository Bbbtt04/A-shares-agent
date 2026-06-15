from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel

from .budget import RuntimeBudget


class AgentRunContext(StrictBaseModel):
    run_id: str
    trading_day: date | None = None
    agent: str
    correlation_id: str | None = None
    permission_profile: str | None = None
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    metadata: dict[str, Any] = Field(default_factory=dict)
