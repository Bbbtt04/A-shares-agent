from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from premarket_contracts import (
    CrawlerProviderResultContract,
    CrawlerResponseContract,
    FetchWindowContract,
    PremarketNewsItemContract,
    PremarketSourceStatusContract,
)

from .registry import default_provider_factories

ProviderFactory = Callable[[], object]


class PremarketCrawlerService:
    def __init__(self, provider_factories: dict[str, ProviderFactory] | None = None) -> None:
        self.provider_factories = provider_factories or default_provider_factories()

    def fetch_source_news(
        self,
        source: str,
        limit: int,
        window: FetchWindowContract,
    ) -> CrawlerProviderResultContract:
        factory = self.provider_factories.get(source)
        if factory is None:
            return CrawlerProviderResultContract(
                source=source,
                provider_name=source,
                status="failed",
                error=f"unknown source: {source}",
            )
        provider = factory()
        try:
            result = provider.fetch(limit=limit, window=window)
        except Exception as error:
            display_name = str(getattr(provider, "source", source))
            provider_name = str(getattr(provider, "provider_name", source))
            return CrawlerProviderResultContract(
                source=display_name,
                provider_name=provider_name,
                status="failed",
                error=str(error),
            )
        return self._normalize_result(result, source)

    def fetch_premarket_news(
        self,
        sources: list[str],
        limit_per_source: int,
        window: FetchWindowContract,
    ) -> CrawlerResponseContract:
        started = perf_counter()
        source_status: list[PremarketSourceStatusContract] = []
        items: list[PremarketNewsItemContract] = []
        warnings: list[str] = []
        for source in sources:
            result = self.fetch_source_news(source, limit=limit_per_source, window=window)
            used_items = window.filter_items(result.items)[:limit_per_source]
            result = result.model_copy(update={"items": used_items})
            items.extend(used_items)
            source_status.append(result.source_status(used_count=len(used_items)))
            if result.status == "failed" and result.error:
                warnings.append(f"{source}: {result.error}")

        failed_count = sum(1 for status in source_status if status.status == "failed")
        ok_count = sum(1 for status in source_status if status.status == "ok")
        if ok_count and failed_count:
            status = "partial"
        elif ok_count:
            status = "ok"
        else:
            status = "failed"
        return CrawlerResponseContract(
            status=status,
            window=window,
            source_status=source_status,
            items=items,
            warnings=warnings,
            metadata={"elapsed_ms": int((perf_counter() - started) * 1000)},
        )

    def _normalize_result(self, result: object, provider_name: str) -> CrawlerProviderResultContract:
        if isinstance(result, CrawlerProviderResultContract):
            return result.model_copy(update={"provider_name": result.provider_name or provider_name})
        source = str(getattr(result, "source", provider_name))
        status = str(getattr(result, "status", "ok"))
        if status not in {"ok", "empty", "failed"}:
            status = "failed"
        raw_items = list(getattr(result, "items", []))
        items = [
            item
            if isinstance(item, PremarketNewsItemContract)
            else PremarketNewsItemContract.model_validate(item.model_dump(mode="json"))
            for item in raw_items
        ]
        return CrawlerProviderResultContract(
            source=source,
            provider_name=provider_name,
            items=items,
            status=status,
            error=getattr(result, "error", None),
        )
