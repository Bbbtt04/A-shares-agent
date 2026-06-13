from __future__ import annotations

from collections.abc import Callable

from premarket_contracts import SourceDescriptor

from .providers import (
    CailianpressTelegraphProvider,
    CsrcNewsProvider,
    DemoPremarketNewsProvider,
    EastMoneyNewsProvider,
    KaipanlaNewsProvider,
    RssNewsProvider,
    SinaFinanceRollProvider,
    TonghuashunNewsProvider,
    XueqiuHotProvider,
)

ProviderFactory = Callable[[], object]


def default_provider_factories() -> dict[str, ProviderFactory]:
    return {
        "demo": DemoPremarketNewsProvider,
        "csrc": CsrcNewsProvider,
        "eastmoney": EastMoneyNewsProvider,
        "sina": SinaFinanceRollProvider,
        "sina_finance": lambda: SinaFinanceRollProvider(
            source="新浪财经滚动", lid="2516", category="sina_finance"
        ),
        "sina_stock": lambda: SinaFinanceRollProvider(
            source="新浪股票滚动", lid="2517", category="sina_stock"
        ),
        "sina_global": lambda: SinaFinanceRollProvider(
            source="新浪全球财经", lid="2518", category="sina_global"
        ),
        "cailianpress": CailianpressTelegraphProvider,
        "kaipanla": KaipanlaNewsProvider,
        "tonghuashun": TonghuashunNewsProvider,
        "xueqiu": XueqiuHotProvider,
    }


def build_rss_provider_factory(source: str, url: str, tier: str = "professional") -> ProviderFactory:
    return lambda: RssNewsProvider(source=source, url=url, tier=tier)


def source_descriptors() -> list[SourceDescriptor]:
    return [
        SourceDescriptor(
            name="csrc",
            display_name="证监会要闻",
            layer="finance_news",
            tier="official",
        ),
        SourceDescriptor(
            name="eastmoney",
            display_name="东方财富财经新闻",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="sina_finance",
            display_name="新浪财经滚动",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="sina_stock",
            display_name="新浪股票滚动",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="sina_global",
            display_name="新浪全球财经",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="tonghuashun",
            display_name="同花顺7x24",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="cailianpress",
            display_name="财联社电报",
            layer="finance_news",
            tier="professional",
        ),
        SourceDescriptor(
            name="kaipanla",
            display_name="开盘啦最新资讯",
            layer="community",
            tier="sentiment",
        ),
        SourceDescriptor(
            name="xueqiu",
            display_name="雪球热议",
            layer="community",
            tier="sentiment",
        ),
    ]
