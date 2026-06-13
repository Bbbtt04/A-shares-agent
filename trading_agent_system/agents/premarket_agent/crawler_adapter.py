from __future__ import annotations

from typing import Protocol

from premarket_contracts import CrawlerResponseContract, FetchWindowContract
from premarket_crawler_mcp.service import PremarketCrawlerService

from trading_agent_system.schemas import PremarketNewsItem, PremarketSourceStatus

from .news_provider import NewsProviderResult


class CrawlerServiceProtocol(Protocol):
    def fetch_premarket_news(
        self,
        sources: list[str],
        limit_per_source: int,
        window: FetchWindowContract,
    ) -> CrawlerResponseContract:
        ...


class LocalPremarketCrawlerProvider:
    source = "premarket-crawler-mcp"

    def __init__(
        self,
        service: CrawlerServiceProtocol | None = None,
        sources: list[str] | None = None,
        source: str | None = None,
    ) -> None:
        self.service = service or PremarketCrawlerService()
        self.sources = sources or []
        if source:
            self.source = source
        self.last_response: CrawlerResponseContract | None = None
        self.last_source_status: list[PremarketSourceStatus] = []

    def fetch(self, limit: int = 30, window: object | None = None) -> NewsProviderResult:
        if window is None:
            raise ValueError("crawler adapter requires a fetch window")
        contract_window = _to_contract_window(window)
        response = self.service.fetch_premarket_news(
            sources=self.sources,
            limit_per_source=limit,
            window=contract_window,
        )
        self.last_response = response
        self.last_source_status = [
            PremarketSourceStatus.model_validate(status.model_dump(mode="json"))
            for status in response.source_status
        ]
        items = [
            PremarketNewsItem.model_validate(item.model_dump(mode="json"))
            for item in response.items
        ]
        if response.status == "failed":
            status = "failed"
        elif items:
            status = "ok"
        else:
            status = "empty"
        error = "; ".join(response.warnings) if response.warnings else None
        return NewsProviderResult(self.source, items, status, error)


def _to_contract_window(window: object) -> FetchWindowContract:
    if isinstance(window, FetchWindowContract):
        return window
    if hasattr(window, "model_dump"):
        return FetchWindowContract.model_validate(window.model_dump(mode="json"))
    return FetchWindowContract(
        mode=getattr(window, "mode"),
        trading_day=getattr(window, "trading_day"),
        previous_trading_day=getattr(window, "previous_trading_day"),
        timezone=getattr(window, "timezone"),
        window_start=getattr(window, "window_start"),
        window_end=getattr(window, "window_end"),
    )
