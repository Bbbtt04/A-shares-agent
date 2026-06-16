from __future__ import annotations

import urllib.request
from typing import Callable

from pydantic import Field

from trading_agent_system.core.reference import ThemeRegistry
from trading_agent_system.schemas import StrictBaseModel


QuoteFetcher = Callable[[list[str]], list[dict[str, object]]]


class AStockCandidate(StrictBaseModel):
    symbol: str
    name: str
    theme: str
    reference_price: float
    entry_low: float
    entry_high: float
    target_price: float
    stop_loss: float
    data_source: str = "a-stock-data/tencent"
    score: float = Field(ge=0, le=2)


class AStockDataAdapter:
    """Small runtime adapter for the installed a-stock-data skill.

    The skill is a Markdown bundle, not an importable package. This adapter
    ports its Tencent quote endpoint into the project so agents can call it.
    """

    def __init__(
        self,
        quote_fetcher: QuoteFetcher | None = None,
        theme_symbols: dict[str, list[str]] | None = None,
    ) -> None:
        self.quote_fetcher = quote_fetcher or fetch_tencent_quotes
        registry = ThemeRegistry.default()
        self.theme_symbols = theme_symbols or registry.theme_symbols

    def candidates_for_theme(self, theme: str, limit: int = 3) -> list[AStockCandidate]:
        symbols = self.theme_symbols.get(theme, [])[: max(1, limit * 2)]
        if not symbols:
            return []
        quotes = self.quote_fetcher(symbols)
        candidates = [
            self._candidate_from_quote(theme, quote)
            for quote in quotes
            if _as_float(quote.get("price")) and str(quote.get("symbol") or "")
        ]
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _candidate_from_quote(self, theme: str, quote: dict[str, object]) -> AStockCandidate:
        price = _as_float(quote.get("price")) or 0.0
        limit_up = _as_float(quote.get("limit_up"))
        limit_down = _as_float(quote.get("limit_down"))
        change_pct = _as_float(quote.get("change_pct")) or 0.0
        vol_ratio = _as_float(quote.get("vol_ratio")) or 1.0
        entry_low = price * 0.99
        entry_high = min(_cap(limit_up, price * 1.02), price * 1.02)
        target_price = min(_cap(limit_up, price * 1.05), price * 1.05)
        stop_loss = max(limit_down or 0, price * 0.97)
        score = min(2.0, max(0.0, 1.0 + change_pct / 100 + min(vol_ratio, 3.0) * 0.05))
        return AStockCandidate(
            symbol=str(quote["symbol"]),
            name=str(quote.get("name") or quote["symbol"]),
            theme=theme,
            reference_price=round(price, 2),
            entry_low=round(entry_low, 2),
            entry_high=round(entry_high, 2),
            target_price=round(target_price, 2),
            stop_loss=round(stop_loss, 2),
            score=round(score, 4),
        )


def fetch_tencent_quotes(symbols: list[str]) -> list[dict[str, object]]:
    prefixed = [_to_tencent_symbol(symbol) for symbol in symbols]
    request = urllib.request.Request(
        "https://qt.gtimg.cn/q=" + ",".join(prefixed),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read().decode("gbk", errors="ignore")
    rows: list[dict[str, object]] = []
    for line in payload.strip().split(";"):
        if not line.strip() or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split("~")
        if len(values) < 53:
            continue
        market = "SH" if key.startswith("sh") else "SZ" if key.startswith("sz") else "BJ" if key.startswith("bj") else "UNKNOWN"
        code = key[2:] if market != "UNKNOWN" else key
        rows.append(
            {
                "symbol": f"{code}.{market}" if market != "UNKNOWN" else code,
                "name": values[1],
                "price": _as_float(values[3]),
                "previous_close": _as_float(values[4]),
                "change_pct": _as_float(values[32]),
                "amount_wan": _as_float(values[37]),
                "turnover_pct": _as_float(values[38]),
                "pe_ttm": _as_float(values[39]),
                "pb": _as_float(values[46]),
                "limit_up": _as_float(values[47]),
                "limit_down": _as_float(values[48]),
                "vol_ratio": _as_float(values[49]),
            }
        )
    return rows


def _to_tencent_symbol(symbol: str) -> str:
    normalized = symbol.strip().lower().replace(".", "")
    if normalized.startswith(("sh", "sz", "bj")):
        return normalized
    code = normalized[:6]
    if symbol.upper().endswith(".SH") or code.startswith(("5", "6", "9")) or code in {"000001", "000300"}:
        return f"sh{code}"
    if symbol.upper().endswith(".BJ") or code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _as_float(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cap(limit: float | None, fallback: float) -> float:
    return limit if limit and limit > 0 else fallback
