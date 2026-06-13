from .schemas import (
    CrawlerProviderResultContract,
    CrawlerRequest,
    CrawlerResponseContract,
    FetchWindowContract,
    PremarketNewsItemContract,
    PremarketSourceStatusContract,
    SourceDescriptor,
    make_id,
    utc_now,
)

FetchWindow = FetchWindowContract
PremarketNewsItem = PremarketNewsItemContract
PremarketSourceStatus = PremarketSourceStatusContract
NewsProviderResult = CrawlerProviderResultContract

__all__ = [
    "CrawlerProviderResultContract",
    "CrawlerRequest",
    "CrawlerResponseContract",
    "FetchWindow",
    "FetchWindowContract",
    "NewsProviderResult",
    "PremarketNewsItem",
    "PremarketNewsItemContract",
    "PremarketSourceStatus",
    "PremarketSourceStatusContract",
    "SourceDescriptor",
    "make_id",
    "utc_now",
]
