# 盘前 news_provider 接入 a-stock-data 实施方案

> **给执行型 Agent 的要求：** 实施本方案时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，并按任务逐项执行。所有步骤使用复选框 `- [ ]` 跟踪状态。

**目标：** 在现有 `PremarketAgent` 的 `news_provider.py` 爬取体系里新增一个 a-stock-data 盘前信息源，只增强盘前报告，不新增独立基建爬虫目录，不改盘中、风控、模拟券商和下单链路。

**架构：** 当前盘前信息就是通过 `trading_agent_system/agents/premarket_agent/news_provider.py` 里的 provider 机制抓取，每个 provider 实现 `fetch(limit, window)` 并返回 `NewsProviderResult`。本方案沿用这个模式，在 `news_provider.py` 中新增 `AStockDataPremarketProvider`，把 a-stock-data 的题材热点、个股新闻、公告和候选股线索映射成现有 `PremarketNewsItem`。`PremarketAgent` 主流程不需要改，只在 `scripts/run_premarket_agent.py` 的 provider 组装阶段按配置加入新 provider。

**技术栈：** Python 3.11+、现有 `PremarketAgent`、现有 `NewsProviderResult` / `PremarketNewsItem`、现有配置加载、pytest。

---

## 一句话结论

当前项目确实已经靠 `news_provider.py` 做盘前爬取，所以这次不抽 `infrastructure/crawlers`。正确落点是：

```text
trading_agent_system/agents/premarket_agent/news_provider.py
```

新增一个 `AStockDataPremarketProvider`，让它像 `EastMoneyNewsProvider`、`SinaFinanceRollProvider`、`TonghuashunNewsProvider` 一样成为盘前信息源。

---

## 范围

要做：

- 在 `news_provider.py` 内新增 `AStockDataPremarketProvider`。
- provider 返回现有 `NewsProviderResult`。
- provider 产生的内容进入现有盘前链路：`source_status`、`news_items`、`catalysts`、`watchlist`、`morning_brief`、`premarket/debug`。
- 在 `configs/app.yaml` 增加开关。
- 在 `scripts/run_premarket_agent.py` 的 `build_providers()` 中按配置加入该 provider。
- 保持失败不影响报告生成：失败时返回 `NewsProviderResult(source, [], "failed", error)`。

不做：

- 不新增 `trading_agent_system/infrastructure/crawlers/`。
- 不改 `PremarketAgent.run()` 主流程。
- 不接入 `IntradayAgent`。
- 不接入 `RiskGateway`。
- 不接入 `PaperBroker`。
- 不把 iwencai 做默认源。

---

## 文件结构

- 修改 `trading_agent_system/agents/premarket_agent/news_provider.py`  
  新增 `AStockDataPremarketProvider`，以及少量私有 helper。

- 修改 `scripts/run_premarket_agent.py`  
  在 provider 工厂中支持 `a_stock_data`。

- 修改 `configs/app.yaml`  
  增加 `premarket.a_stock_data` 配置。

- 修改 `tests/premarket/test_social_news_providers.py` 或新增 `tests/premarket/test_a_stock_data_news_provider.py`  
  覆盖 provider 映射、失败降级、时间窗口过滤。

- 修改 `tests/premarket/test_premarket_provider_config.py`  
  覆盖配置接入。

- 保留 `trading_agent_system/core/market_data/a_stock_data.py`  
  现有候选股适配器可以继续用于 watchlist 候选股，不把它搬到新基建层。

---

## 数据映射设计

`AStockDataPremarketProvider` 统一输出 `PremarketNewsItem`：

| a-stock-data 数据 | `PremarketNewsItem.category` | `source_tier` | 说明 |
| --- | --- | --- | --- |
| 同花顺热点/强势股 | `theme_hotspot` | `professional` | 题材和强势股线索 |
| 东财个股新闻 | `stock_news` | `professional` | 个股催化补充 |
| 巨潮公告 | `announcement` | `official` | 公告确认和风险识别 |
| 腾讯行情候选股摘要 | `quote_candidate` | `professional` | 只作为观察线索，不当成交易信号 |

默认置信度建议：

```text
announcement: 0.90
theme_hotspot: 0.72
stock_news: 0.68
quote_candidate: 0.60
```

---

## 任务 1：新增 AStockDataPremarketProvider 的 provider 测试

**文件：**

- 新增：`tests/premarket/test_a_stock_data_news_provider.py`

- [ ] **步骤 1：写失败测试**

创建 `tests/premarket/test_a_stock_data_news_provider.py`：

```python
from datetime import datetime, timezone

from trading_agent_system.agents.premarket_agent.news_provider import (
    AStockDataPremarketProvider,
    FetchWindow,
)


def test_a_stock_data_provider_maps_rows_to_news_items():
    published_at = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    window = FetchWindow(
        window_start=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 9, 1, 30, tzinfo=timezone.utc),
        mode="premarket",
    )
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [
            {
                "title": "半导体强势股活跃",
                "theme": "半导体",
                "symbol": "688981.SH",
                "summary": "国产替代与政策催化",
                "published_at": published_at,
            }
        ],
        stock_news_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际获得设备采购订单",
                "summary": "订单扩张，需等待公告确认。",
                "symbol": "688981.SH",
                "url": "https://example.test/news",
                "published_at": published_at,
            }
        ],
        announcement_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际关于设备采购合同的公告",
                "summary": "临时公告",
                "symbol": "688981.SH",
                "url": "https://example.test/ann",
                "published_at": published_at,
            }
        ],
        quote_candidate_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际盘前观察候选",
                "summary": "参考价 90.0，目标价 94.5，止损 87.3。",
                "symbol": "688981.SH",
                "theme": "半导体",
                "published_at": published_at,
            }
        ],
        symbols=["688981.SH"],
    )

    result = provider.fetch(limit=10, window=window)

    assert result.source == "a-stock-data/premarket"
    assert result.status == "ok"
    assert [item.category for item in result.items] == [
        "theme_hotspot",
        "stock_news",
        "announcement",
        "quote_candidate",
    ]
    assert result.items[0].sectors == ["半导体"]
    assert result.items[0].symbols == ["688981.SH"]
    assert result.items[2].source_tier == "official"
```

- [ ] **步骤 2：运行测试，确认失败原因正确**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_news_provider.py::test_a_stock_data_provider_maps_rows_to_news_items -q
```

预期：失败，错误包含 `ImportError` 或 `cannot import name 'AStockDataPremarketProvider'`。

- [ ] **步骤 3：提交测试**

```bash
git add tests/premarket/test_a_stock_data_news_provider.py
git commit -m "test: describe a-stock-data premarket news provider"
```

---

## 任务 2：在 news_provider.py 实现 AStockDataPremarketProvider

**文件：**

- 修改：`trading_agent_system/agents/premarket_agent/news_provider.py`
- 测试：`tests/premarket/test_a_stock_data_news_provider.py`

- [ ] **步骤 1：在 news_provider.py 增加 provider**

在 `news_provider.py` 中追加如下实现。放在其他 provider 类附近即可，建议放在 `TonghuashunNewsProvider` 后面或 `DemoPremarketNewsProvider` 前面：

```python
class AStockDataPremarketProvider:
    source = "a-stock-data/premarket"

    def __init__(
        self,
        hotspot_fetcher=None,
        stock_news_fetcher=None,
        announcement_fetcher=None,
        quote_candidate_fetcher=None,
        symbols: list[str] | None = None,
    ) -> None:
        self.hotspot_fetcher = hotspot_fetcher or self._fetch_hotspots
        self.stock_news_fetcher = stock_news_fetcher or self._fetch_stock_news
        self.announcement_fetcher = announcement_fetcher or self._fetch_announcements
        self.quote_candidate_fetcher = quote_candidate_fetcher or self._fetch_quote_candidates
        self.symbols = symbols or []

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        try:
            rows = [
                *self._tag_rows(self.hotspot_fetcher(limit), "theme_hotspot", "professional", 0.72),
                *self._tag_rows(self.stock_news_fetcher(self.symbols, limit), "stock_news", "professional", 0.68),
                *self._tag_rows(self.announcement_fetcher(self.symbols, limit), "announcement", "official", 0.90),
                *self._tag_rows(self.quote_candidate_fetcher(self.symbols, limit), "quote_candidate", "professional", 0.60),
            ]
            items = [self._row_to_item(row) for row in rows]
            items = _filter_items_for_window([item for item in items if item.title], window)
            items = _apply_limit(items, limit)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _tag_rows(
        self,
        rows: list[dict[str, object]],
        category: str,
        source_tier: str,
        credibility: float,
    ) -> list[dict[str, object]]:
        tagged = []
        for row in rows:
            item = dict(row)
            item["category"] = category
            item["source_tier"] = source_tier
            item["credibility"] = credibility
            tagged.append(item)
        return tagged

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        symbol = _as_text(row.get("symbol"))
        theme = _as_text(row.get("theme"))
        return PremarketNewsItem(
            source=self.source,
            provider_name="a-stock-data",
            source_tier=_as_text(row.get("source_tier")) or "professional",
            title=_as_text(row.get("title")),
            summary=_as_text(row.get("summary")),
            url=_as_text(row.get("url")) or None,
            published_at=row.get("published_at") if isinstance(row.get("published_at"), datetime) else None,
            category=_as_text(row.get("category")) or "unknown",
            symbols=[symbol] if symbol else [],
            sectors=[theme] if theme else [],
            credibility=float(row.get("credibility") or 0.6),
        )

    def _fetch_hotspots(self, limit: int | None = None) -> list[dict[str, object]]:
        return []

    def _fetch_stock_news(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        return []

    def _fetch_announcements(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        return []

    def _fetch_quote_candidates(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        return []
```

如果 `news_provider.py` 里还没有 `_as_text()`，新增一个私有 helper：

```python
def _as_text(value: object) -> str:
    return str(value or "").strip()
```

- [ ] **步骤 2：运行 provider 测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_news_provider.py -q
```

预期：通过。

- [ ] **步骤 3：运行盘前 provider 相关测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket/test_social_news_providers.py tests\premarket\test_a_stock_data_news_provider.py -q
```

预期：通过。

- [ ] **步骤 4：提交实现**

```bash
git add trading_agent_system/agents/premarket_agent/news_provider.py tests/premarket/test_a_stock_data_news_provider.py
git commit -m "feat: add a-stock-data premarket news provider"
```

---

## 任务 3：给 AStockDataPremarketProvider 增加失败降级和窗口过滤测试

**文件：**

- 修改：`tests/premarket/test_a_stock_data_news_provider.py`

- [ ] **步骤 1：追加失败降级测试**

```python
from datetime import datetime, timezone


def test_a_stock_data_provider_returns_failed_result_when_fetcher_raises():
    def boom(limit):
        raise RuntimeError("upstream timeout")

    provider = AStockDataPremarketProvider(
        hotspot_fetcher=boom,
        symbols=["688981.SH"],
    )

    result = provider.fetch(limit=5)

    assert result.source == "a-stock-data/premarket"
    assert result.status == "failed"
    assert result.items == []
    assert "upstream timeout" in (result.error or "")
```

- [ ] **步骤 2：追加窗口过滤测试**

```python
def test_a_stock_data_provider_filters_items_outside_premarket_window():
    inside = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    outside = datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc)
    window = FetchWindow(
        window_start=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 9, 1, 30, tzinfo=timezone.utc),
        mode="premarket",
    )
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [
            {"title": "窗口内热点", "theme": "半导体", "published_at": inside},
            {"title": "窗口外热点", "theme": "半导体", "published_at": outside},
        ],
    )

    result = provider.fetch(limit=10, window=window)

    assert [item.title for item in result.items] == ["窗口内热点"]
```

- [ ] **步骤 3：运行测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_news_provider.py -q
```

预期：通过。

- [ ] **步骤 4：提交**

```bash
git add tests/premarket/test_a_stock_data_news_provider.py
git commit -m "test: cover a-stock-data provider fallback and window filtering"
```

---

## 任务 4：通过配置接入 run_premarket_agent.py

**文件：**

- 修改：`configs/app.yaml`
- 修改：`scripts/run_premarket_agent.py`
- 修改：`tests/premarket/test_premarket_provider_config.py`

- [ ] **步骤 1：写配置接入失败测试**

在 `tests/premarket/test_premarket_provider_config.py` 中添加：

```python
from scripts.run_premarket_agent import build_providers
from trading_agent_system.agents.premarket_agent.news_provider import AStockDataPremarketProvider


def test_build_providers_adds_a_stock_data_provider_when_enabled():
    providers = build_providers(
        {
            "premarket": {
                "providers": [],
                "a_stock_data": {
                    "enabled": True,
                    "symbols": ["688981.SH", "002371.SZ"],
                },
            }
        }
    )

    assert any(isinstance(provider, AStockDataPremarketProvider) for provider in providers)
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_premarket_provider_config.py::test_build_providers_adds_a_stock_data_provider_when_enabled -q
```

预期：失败，因为 `build_providers()` 还没有加入该 provider。

- [ ] **步骤 3：修改配置**

在 `configs/app.yaml` 的 `premarket` 下增加：

```yaml
  a_stock_data:
    enabled: true
    symbols:
      - 688981.SH
      - 002371.SZ
      - 688256.SH
      - 601138.SH
```

- [ ] **步骤 4：修改 run_premarket_agent.py 导入**

在 `scripts/run_premarket_agent.py` 的 provider imports 中加入：

```python
from trading_agent_system.agents.premarket_agent.news_provider import AStockDataPremarketProvider
```

如果该文件已经用括号批量导入 provider，则把 `AStockDataPremarketProvider` 放进同一个导入列表。

- [ ] **步骤 5：增加 provider 构造 helper**

在 `scripts/run_premarket_agent.py` 中新增：

```python
def build_a_stock_data_provider(app_config: dict[str, object]) -> object | None:
    premarket = app_config.get("premarket", {})
    if not isinstance(premarket, dict):
        return None
    config = premarket.get("a_stock_data", {})
    if not isinstance(config, dict) or not config.get("enabled", False):
        return None
    symbols = [str(symbol) for symbol in config.get("symbols", []) if symbol]
    return AStockDataPremarketProvider(symbols=symbols)
```

在 `build_providers()` 结尾、RSS feeds 追加之后加入：

```python
    a_stock_data_provider = build_a_stock_data_provider(app_config)
    if a_stock_data_provider is not None:
        providers.append(a_stock_data_provider)
```

- [ ] **步骤 6：运行配置测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_premarket_provider_config.py -q
```

预期：通过。

- [ ] **步骤 7：提交**

```bash
git add configs/app.yaml scripts/run_premarket_agent.py tests/premarket/test_premarket_provider_config.py
git commit -m "feat: wire a-stock-data provider into premarket config"
```

---

## 任务 5：把默认 fetcher 接到现有 a_stock_data 适配能力

**文件：**

- 修改：`trading_agent_system/agents/premarket_agent/news_provider.py`
- 可选修改：`trading_agent_system/core/market_data/a_stock_data.py`
- 测试：`tests/premarket/test_a_stock_data_news_provider.py`

- [ ] **步骤 1：写 quote candidate 默认 fetcher 测试**

在 `tests/premarket/test_a_stock_data_news_provider.py` 中追加：

```python
def test_a_stock_data_provider_builds_quote_candidate_rows_from_adapter():
    class FakeAdapter:
        def candidates_for_theme(self, theme: str, limit: int = 3):
            class Candidate:
                symbol = "688981.SH"
                name = "中芯国际"
                theme = "半导体"
                reference_price = 90.0
                target_price = 94.5
                stop_loss = 87.3
                data_source = "a-stock-data/tencent"

            return [Candidate()]

    provider = AStockDataPremarketProvider(
        symbols=["688981.SH"],
        theme_symbols={"半导体": ["688981.SH"]},
        stock_data_adapter=FakeAdapter(),
    )

    rows = provider._fetch_quote_candidates(["688981.SH"], limit=5)

    assert rows == [
        {
            "title": "中芯国际(688981.SH) 盘前观察候选",
            "summary": "半导体候选，参考价 90.0，目标价 94.5，止损 87.3，来源 a-stock-data/tencent。",
            "symbol": "688981.SH",
            "theme": "半导体",
        }
    ]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_news_provider.py::test_a_stock_data_provider_builds_quote_candidate_rows_from_adapter -q
```

预期：失败，因为 `AStockDataPremarketProvider` 还不支持 `stock_data_adapter` / `theme_symbols`。

- [ ] **步骤 3：给 provider 增加可选 adapter**

修改 `AStockDataPremarketProvider.__init__`：

```python
    def __init__(
        self,
        hotspot_fetcher=None,
        stock_news_fetcher=None,
        announcement_fetcher=None,
        quote_candidate_fetcher=None,
        symbols: list[str] | None = None,
        theme_symbols: dict[str, list[str]] | None = None,
        stock_data_adapter=None,
    ) -> None:
        self.hotspot_fetcher = hotspot_fetcher or self._fetch_hotspots
        self.stock_news_fetcher = stock_news_fetcher or self._fetch_stock_news
        self.announcement_fetcher = announcement_fetcher or self._fetch_announcements
        self.quote_candidate_fetcher = quote_candidate_fetcher or self._fetch_quote_candidates
        self.symbols = symbols or []
        self.theme_symbols = theme_symbols or {}
        self.stock_data_adapter = stock_data_adapter
```

实现 `_fetch_quote_candidates()`：

```python
    def _fetch_quote_candidates(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        if self.stock_data_adapter is None:
            return []
        rows: list[dict[str, object]] = []
        max_rows = limit or 20
        for theme, theme_symbols in self.theme_symbols.items():
            if symbols and not set(symbols).intersection(theme_symbols):
                continue
            for candidate in self.stock_data_adapter.candidates_for_theme(theme, limit=3):
                rows.append(
                    {
                        "title": f"{candidate.name}({candidate.symbol}) 盘前观察候选",
                        "summary": (
                            f"{candidate.theme}候选，参考价 {candidate.reference_price}，"
                            f"目标价 {candidate.target_price}，止损 {candidate.stop_loss}，"
                            f"来源 {candidate.data_source}。"
                        ),
                        "symbol": candidate.symbol,
                        "theme": candidate.theme,
                    }
                )
                if len(rows) >= max_rows:
                    return rows
        return rows
```

- [ ] **步骤 4：在 run_premarket_agent.py 构造 provider 时传 adapter**

如果项目已存在 `AStockDataAdapter`，在 `build_a_stock_data_provider()` 中传入：

```python
from trading_agent_system.core.market_data import AStockDataAdapter
from trading_agent_system.core.reference import ThemeRegistry
```

构造处改为：

```python
    registry = ThemeRegistry.default()
    return AStockDataPremarketProvider(
        symbols=symbols,
        theme_symbols=registry.theme_symbols,
        stock_data_adapter=AStockDataAdapter(),
    )
```

- [ ] **步骤 5：运行测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_news_provider.py tests\premarket\test_premarket_provider_config.py -q
```

预期：通过。

- [ ] **步骤 6：提交**

```bash
git add trading_agent_system/agents/premarket_agent/news_provider.py scripts/run_premarket_agent.py tests/premarket/test_a_stock_data_news_provider.py
git commit -m "feat: add a-stock-data quote candidates to premarket provider"
```

---

## 任务 6：PremarketAgent 集成验证

**文件：**

- 修改：`tests/premarket/test_a_stock_data_integration.py`

- [ ] **步骤 1：写端到端集成测试**

追加测试：

```python
from datetime import date, datetime, timezone

from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.news_provider import AStockDataPremarketProvider
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.storage import JsonlEventRepository


def test_premarket_agent_uses_a_stock_data_news_provider(tmp_path):
    published_at = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [
            {
                "title": "半导体强势股活跃",
                "theme": "半导体",
                "symbol": "688981.SH",
                "summary": "国产替代与政策催化",
                "published_at": published_at,
            }
        ],
        stock_news_fetcher=lambda symbols, limit: [],
        announcement_fetcher=lambda symbols, limit: [],
        quote_candidate_fetcher=lambda symbols, limit: [],
        symbols=["688981.SH"],
    )
    agent = PremarketAgent(
        event_bus=DurableEventBus(repository=JsonlEventRepository(tmp_path / "events")),
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        providers=[provider],
        calendar=TradingCalendarService(),
    )

    report = agent.run(date(2026, 6, 9), limit_per_source=5)

    assert report.source_status[0].source == "a-stock-data/premarket"
    assert report.source_status[0].status == "ok"
    assert report.news_items[0].category == "theme_hotspot"
    assert any(catalyst.sectors == ["半导体"] for catalyst in report.catalysts)
```

- [ ] **步骤 2：运行单测**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket\test_a_stock_data_integration.py::test_premarket_agent_uses_a_stock_data_news_provider -q
```

预期：通过。

- [ ] **步骤 3：运行全部盘前测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket -q
```

预期：通过。

- [ ] **步骤 4：提交**

```bash
git add tests/premarket/test_a_stock_data_integration.py
git commit -m "test: cover a-stock-data premarket provider integration"
```

---

## 任务 7：最终验证

**文件：**

- 不新增文件。

- [ ] **步骤 1：运行目标测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest tests\premarket tests\market_data -q
```

预期：全部通过。

- [ ] **步骤 2：运行全量测试**

运行：

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

预期：全部通过。

- [ ] **步骤 3：做一次真实盘前 smoke**

运行：

```bash
.\.venv\Scripts\python.exe scripts\run_premarket_agent.py --date 2026-06-09 --config configs/app.yaml --limit 5
```

预期：

- 命令退出码为 0。
- JSON stdout 的 `source_status` 中包含 `"source": "a-stock-data/premarket"`。
- 如果公开接口失败，`source_status` 中该源为 `"status": "failed"`，但进程仍退出 0。

---

## 自检

需求覆盖：

- “现在靠 `news_provider.py` 爬”：本方案已改为在 `news_provider.py` 新增 provider。
- “目前只加到盘前信息”：本方案只接 `PremarketAgent.providers`。
- 不新增基建层目录：已明确不新增 `infrastructure/crawlers`。
- 配置可控：任务 4 覆盖。
- 失败不影响报告：任务 3 覆盖。
- 可进入现有报告链路：任务 6 覆盖。

类型一致性：

- `AStockDataPremarketProvider.fetch(limit, window)` 与现有 provider contract 一致。
- 返回 `NewsProviderResult`。
- item 类型是现有 `PremarketNewsItem`。
- `scripts/run_premarket_agent.py` 只负责组装 provider，不改 `PremarketAgent` 主流程。
