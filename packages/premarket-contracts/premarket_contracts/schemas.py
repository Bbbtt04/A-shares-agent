from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class StrictBaseModel(BaseModel):
    model_config = {"extra": "forbid", "use_enum_values": True}


class PremarketNewsItemContract(StrictBaseModel):
    item_id: str = Field(default_factory=lambda: make_id("news"))
    source: str
    provider_name: str | None = None
    source_tier: Literal["official", "professional", "sentiment", "unknown"] = "unknown"
    title: str
    summary: str = ""
    url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    category: str = "unknown"
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    credibility: float = Field(default=0.5, ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)


class PremarketSourceStatusContract(StrictBaseModel):
    source: str
    provider_name: str | None = None
    status: Literal["ok", "empty", "failed"]
    fetched_count: int = 0
    used_count: int = 0
    error: str | None = None


class FetchWindowContract(StrictBaseModel):
    mode: Literal["premarket", "post_close"]
    trading_day: date
    previous_trading_day: date
    timezone: str
    window_start: datetime
    window_end: datetime

    def contains(self, published_at: datetime | None) -> bool:
        if published_at is None:
            return False
        published = published_at.astimezone(ZoneInfo(self.timezone))
        return self.window_start <= published < self.window_end

    def filter_items(self, items: list[PremarketNewsItemContract]) -> list[PremarketNewsItemContract]:
        return [item for item in items if self.contains(item.published_at)]


class CrawlerProviderResultContract(StrictBaseModel):
    source: str
    items: list[PremarketNewsItemContract] = Field(default_factory=list)
    provider_name: str | None = None
    status: Literal["ok", "empty", "failed"] = "ok"
    error: str | None = None

    def source_status(self, used_count: int) -> PremarketSourceStatusContract:
        return PremarketSourceStatusContract(
            source=self.source,
            provider_name=self.provider_name or self.source,
            status=self.status,
            fetched_count=len(self.items),
            used_count=used_count,
            error=self.error,
        )


class CrawlerRequest(StrictBaseModel):
    sources: list[str] = Field(default_factory=list)
    limit_per_source: int = Field(default=30, gt=0)
    window: FetchWindowContract


class CrawlerResponseContract(StrictBaseModel):
    status: Literal["ok", "partial", "failed"]
    window: FetchWindowContract
    source_status: list[PremarketSourceStatusContract] = Field(default_factory=list)
    items: list[PremarketNewsItemContract] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDescriptor(StrictBaseModel):
    name: str
    display_name: str
    layer: Literal["stock_info", "finance_news", "community"]
    tier: Literal["official", "professional", "sentiment", "unknown"] = "unknown"
    enabled_by_default: bool = True
    auth_required: bool = False
