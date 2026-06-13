from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class EvidenceReference(StrictBaseModel):
    evidence_id: str
    source: str | None = None
    citation_label: str | None = None


class AgentConclusion(StrictBaseModel):
    kind: Literal["fact", "inference", "view", "risk"]
    statement: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class AgentOutputEnvelope(StrictBaseModel):
    agent: str
    run_id: str | None = None
    conclusions: list[AgentConclusion] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    output_id: str = Field(default_factory=lambda: make_id("agent_output"))
    created_at: datetime = Field(default_factory=utc_now)
