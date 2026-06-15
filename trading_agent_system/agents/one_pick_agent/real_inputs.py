from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_agent_system.core.market_data import EastMoneyMarketDataProvider, TencentMarketDataProvider
from trading_agent_system.core.storage import JsonlEventRepository


CSI1000_INDEX_ID = "000852"
SINA_COMPONENT_URL = "https://vip.stock.finance.sina.com.cn/corp/view/vII_NewestComponent.php"


@dataclass(frozen=True)
class UniverseConfig:
    symbols: list[str]
    source: str
    universe_id: str = "csi1000"
    names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RealOnePickInputs:
    events: list[dict[str, Any]]
    event_clusters: list[dict[str, Any]]
    evidence_packs: list[dict[str, Any]]
    market_snapshots: dict[str, dict[str, Any]]
    metadata: dict[str, Any]


class MarketProvider(Protocol):
    def fetch_quotes(self, symbols: list[str]) -> list[Any]:
        ...


class FallbackMarketDataProvider:
    def __init__(self, providers: list[MarketProvider] | None = None) -> None:
        self.providers = providers or [EastMoneyMarketDataProvider(), TencentMarketDataProvider()]

    def fetch_quotes(self, symbols: list[str]) -> list[Any]:
        last_error: Exception | None = None
        for provider in self.providers:
            try:
                quotes = provider.fetch_quotes(symbols)
            except Exception as error:
                last_error = error
                continue
            if quotes:
                return quotes
        if last_error is not None:
            raise last_error
        return []


class RealOnePickInputBuilder:
    def __init__(
        self,
        *,
        event_dir: str | Path = "data/events",
        universe: UniverseConfig | None = None,
        theme_symbol_map: dict[str, list[str]] | None = None,
        market_provider: MarketProvider | None = None,
    ) -> None:
        self.event_dir = Path(event_dir)
        self.universe = universe or load_csi1000_universe()
        self.theme_symbol_map = theme_symbol_map or default_theme_symbol_map()
        self.market_provider = market_provider or FallbackMarketDataProvider()

    def build(self, *, trading_day: date | None = None) -> RealOnePickInputs:
        repository = JsonlEventRepository(self.event_dir)
        events = _latest_payload_items(repository, "premarket.normalized_events", "items", trading_day=trading_day)
        clusters = _latest_payload_items(repository, "premarket.event_clusters", "items", trading_day=trading_day)
        evidence_packs = _latest_payload_items(repository, "premarket.rag_evidence_packs", "packs", trading_day=trading_day)
        universe_symbols = set(self.universe.symbols)
        events = expand_events_with_theme_symbols(
            events,
            universe_symbols=universe_symbols,
            theme_symbol_map=self.theme_symbol_map,
            symbol_names=self.universe.names,
        )
        clusters = expand_events_with_theme_symbols(
            clusters,
            universe_symbols=universe_symbols,
            theme_symbol_map=self.theme_symbol_map,
            symbol_names=self.universe.names,
        )
        evidence_packs = _filter_symbol_payloads(evidence_packs, universe_symbols, self.universe.names)
        candidate_symbols = _candidate_symbols(events, clusters, evidence_packs)
        market_snapshots = self._fetch_market_snapshots(candidate_symbols)
        return RealOnePickInputs(
            events=events,
            event_clusters=clusters,
            evidence_packs=evidence_packs,
            market_snapshots=market_snapshots,
            metadata={
                "source": "real",
                "universe": self.universe.universe_id,
                "universe_source": self.universe.source,
                "universe_size": len(self.universe.symbols),
                "candidate_symbol_count": len(candidate_symbols),
            },
        )

    def _fetch_market_snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        try:
            quotes = self.market_provider.fetch_quotes(symbols[:80])
        except Exception as error:
            return {symbol: {"symbol": symbol, "last_price": 1.0, "quote_error": str(error)} for symbol in symbols[:80]}
        snapshots: dict[str, dict[str, Any]] = {}
        for quote in quotes:
            data = _to_dict(quote)
            symbol = str(data.get("symbol") or "")
            if not symbol:
                continue
            price = data.get("price") or data.get("last_price") or data.get("close")
            snapshots[symbol] = {
                **data,
                "last_price": float(price) if price not in (None, "", "-") else 1.0,
            }
        for symbol in symbols:
            snapshots.setdefault(symbol, {"symbol": symbol, "last_price": 1.0})
        return snapshots


def expand_events_with_theme_symbols(
    events: list[dict[str, Any]],
    *,
    universe_symbols: set[str],
    theme_symbol_map: dict[str, list[str]],
    symbol_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        symbols = [_normalize_symbol(symbol) for symbol in item.get("symbols", []) or []]
        symbols = [symbol for symbol in symbols if symbol in universe_symbols]
        symbol_source = "event_symbols" if symbols else None
        if not symbols:
            symbols = _symbols_for_themes(
                [*(item.get("related_themes", []) or []), item.get("title", "")],
                theme_symbol_map,
                universe_symbols,
            )
            symbol_source = "theme_map" if symbols else None
        item["symbols"] = symbols
        if symbol_source:
            item["symbol_source"] = symbol_source
        if symbol_names and symbols and not item.get("name"):
            item["name"] = symbol_names.get(symbols[0])
        expanded.append(item)
    return expanded


def load_csi1000_universe(config_path: str | Path = "configs/universe.csi1000.yaml") -> UniverseConfig:
    configured = _load_universe_config(Path(config_path))
    try:
        online = fetch_sina_index_components(CSI1000_INDEX_ID)
    except Exception:
        online = UniverseConfig(symbols=[], source="sina_unavailable")
    if online.symbols:
        return online
    if configured.symbols:
        return configured
    return UniverseConfig(symbols=_fallback_csi1000_symbols(), source="fallback_seed")


def fetch_sina_index_components(index_id: str = CSI1000_INDEX_ID, *, timeout_seconds: int = 10) -> UniverseConfig:
    first_page = _fetch_sina_component_page(index_id, 1, timeout_seconds)
    total_pages = _extract_total_pages(first_page) or 1
    symbols, names = _extract_sina_components(first_page)
    for page in range(2, min(total_pages, 60) + 1):
        time.sleep(0.05)
        page_symbols, page_names = _extract_sina_components(
            _fetch_sina_component_page(index_id, page, timeout_seconds)
        )
        symbols.extend(page_symbols)
        names.update(page_names)
    unique_symbols = _unique(symbols)
    return UniverseConfig(symbols=unique_symbols, names=names, source=f"sina_index_{index_id}")


def default_theme_symbol_map() -> dict[str, list[str]]:
    return {
        "消费": ["000973.SZ", "300755.SZ", "002557.SZ", "300146.SZ"],
        "券商": ["601162.SH", "601108.SH", "002500.SZ", "600109.SH"],
        "公告": ["300024.SZ", "000973.SZ", "300308.SZ", "300502.SZ"],
        "机器人": ["300024.SZ", "002747.SZ", "300276.SZ", "688160.SH"],
        "人工智能": ["300229.SZ", "300418.SZ", "688256.SH", "300033.SZ"],
        "AI": ["300229.SZ", "300418.SZ", "688256.SH", "300033.SZ"],
        "半导体": ["688981.SH", "688012.SH", "300661.SZ", "002371.SZ"],
        "芯片": ["688981.SH", "688012.SH", "300661.SZ", "002371.SZ"],
        "新能源": ["300750.SZ", "300274.SZ", "002709.SZ", "688599.SH"],
        "储能": ["300274.SZ", "002335.SZ", "688390.SH", "300693.SZ"],
        "医药": ["300760.SZ", "300015.SZ", "688271.SH", "300347.SZ"],
        "军工": ["300395.SZ", "600765.SH", "300474.SZ", "688297.SH"],
        "低空经济": ["600316.SH", "300424.SZ", "002085.SZ", "300719.SZ"],
        "算力": ["300308.SZ", "300502.SZ", "603019.SH", "300394.SZ"],
    }


def _latest_payload_items(
    repository: JsonlEventRepository,
    topic: str,
    key: str,
    *,
    trading_day: date | None,
) -> list[dict[str, Any]]:
    envelopes = repository.load_envelopes(topic, trading_day=trading_day, limit=1)
    if trading_day is not None and not envelopes:
        envelopes = repository.load_envelopes(topic, limit=1)
    if not envelopes:
        return []
    payload = envelopes[-1].payload
    raw_items = payload.get(key) or payload.get("items") or payload.get("clusters") or payload.get("value") or []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    return [dict(item) for item in raw_items if isinstance(item, dict)]


def _filter_symbol_payloads(
    payloads: list[dict[str, Any]],
    universe_symbols: set[str],
    symbol_names: dict[str, str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for payload in payloads:
        item = dict(payload)
        symbols = [_normalize_symbol(symbol) for symbol in item.get("symbols", []) or []]
        item["symbols"] = [symbol for symbol in symbols if symbol in universe_symbols]
        if item["symbols"] and not item.get("name"):
            item["name"] = symbol_names.get(item["symbols"][0])
        filtered.append(item)
    return filtered


def _candidate_symbols(*groups: list[dict[str, Any]]) -> list[str]:
    symbols: list[str] = []
    for group in groups:
        for item in group:
            symbols.extend(str(symbol) for symbol in item.get("symbols", []) or [])
    return _unique(symbols)


def _symbols_for_themes(
    themes: list[Any],
    theme_symbol_map: dict[str, list[str]],
    universe_symbols: set[str],
) -> list[str]:
    symbols: list[str] = []
    haystack = " ".join(str(theme) for theme in themes)
    for key, mapped_symbols in theme_symbol_map.items():
        if key and key in haystack:
            symbols.extend(_normalize_symbol(symbol) for symbol in mapped_symbols)
    return [symbol for symbol in _unique(symbols) if symbol in universe_symbols]


def _load_universe_config(path: Path) -> UniverseConfig:
    if not path.exists():
        return UniverseConfig(symbols=[], source="missing_config")
    try:
        import yaml  # type: ignore
    except ImportError:
        return UniverseConfig(symbols=[], source="yaml_unavailable")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    symbols = [_normalize_symbol(item) for item in data.get("symbols", [])]
    names = {str(key): str(value) for key, value in (data.get("names") or {}).items()}
    return UniverseConfig(
        symbols=_unique([symbol for symbol in symbols if symbol]),
        source=str(data.get("source") or "local_config"),
        universe_id=str(data.get("universe_id") or "csi1000"),
        names=names,
    )


def _fetch_sina_component_page(index_id: str, page: int, timeout_seconds: int) -> str:
    query = urlencode({"indexid": index_id, "page": page})
    url = f"{SINA_COMPONENT_URL}?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("gb18030", errors="ignore")
    except (OSError, URLError):
        completed = subprocess.run(
            [
                "curl",
                "-sS",
                "-L",
                "--connect-timeout",
                str(timeout_seconds),
                "--max-time",
                str(timeout_seconds + 5),
                "-H",
                "User-Agent: Mozilla/5.0",
                url,
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            raise RuntimeError(completed.stderr.decode("utf-8", errors="ignore") or "sina component fetch failed")
        return completed.stdout.decode("gb18030", errors="ignore")


def _extract_sina_components(html: str) -> tuple[list[str], dict[str, str]]:
    rows = re.findall(
        r"<td><div align=\"center\">(\d{6})</div></td>\s*"
        r"<td><div align=\"center\"><a [^>]*>(.*?)</a></div></td>",
        html,
        flags=re.S,
    )
    symbols: list[str] = []
    names: dict[str, str] = {}
    for code, raw_name in rows:
        symbol = _normalize_symbol(code)
        name = re.sub(r"<.*?>", "", raw_name).strip()
        symbols.append(symbol)
        names[symbol] = name
    return symbols, names


def _extract_total_pages(html: str) -> int | None:
    match = re.search(r"共(\d+)页", html)
    return int(match.group(1)) if match else None


def _normalize_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if not text:
        return ""
    if "." in text:
        code, market = text.split(".", 1)
        return f"{code}.{market}"
    if text.startswith(("5", "6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "1", "2", "3")):
        return f"{text}.SZ"
    return text


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _fallback_csi1000_symbols() -> list[str]:
    return [
        "000973.SZ",
        "300024.SZ",
        "002747.SZ",
        "300276.SZ",
        "300229.SZ",
        "300418.SZ",
        "688256.SH",
        "300033.SZ",
        "300661.SZ",
        "002371.SZ",
        "300274.SZ",
        "002709.SZ",
        "300760.SZ",
        "300015.SZ",
        "300395.SZ",
        "600765.SH",
        "600316.SH",
        "300424.SZ",
        "300308.SZ",
        "300502.SZ",
    ]
