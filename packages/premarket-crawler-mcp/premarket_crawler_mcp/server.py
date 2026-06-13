from __future__ import annotations

from datetime import date, datetime
from typing import Any

from premarket_contracts import FetchWindowContract

from .registry import source_descriptors
from .service import PremarketCrawlerService

try:  # pragma: no cover - depends on optional runtime package during local tests
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]


VERSION = "0.1.0"


def health() -> dict[str, str]:
    return {"status": "ok", "service": "premarket-crawler-mcp", "version": VERSION}


def list_sources() -> dict[str, list[dict[str, Any]]]:
    return {"sources": [source.model_dump(mode="json") for source in source_descriptors()]}


def fetch_source_news(source: str, limit: int, window: dict[str, Any]) -> dict[str, Any]:
    parsed_window = _parse_window(window)
    result = PremarketCrawlerService().fetch_source_news(source=source, limit=limit, window=parsed_window)
    return result.model_dump(mode="json")


def fetch_premarket_news(
    sources: list[str],
    limit_per_source: int,
    window: dict[str, Any],
) -> dict[str, Any]:
    parsed_window = _parse_window(window)
    result = PremarketCrawlerService().fetch_premarket_news(
        sources=sources,
        limit_per_source=limit_per_source,
        window=parsed_window,
    )
    return result.model_dump(mode="json")


def create_mcp_server() -> object:
    if FastMCP is None:
        raise RuntimeError("mcp package is not installed")
    server = FastMCP("premarket-crawler-mcp")
    server.tool()(health)
    server.tool()(list_sources)
    server.tool()(fetch_source_news)
    server.tool()(fetch_premarket_news)
    return server


def main() -> None:
    server = create_mcp_server()
    server.run()  # type: ignore[attr-defined]


def _parse_window(value: dict[str, Any]) -> FetchWindowContract:
    payload = dict(value)
    for key in ("trading_day", "previous_trading_day"):
        if isinstance(payload.get(key), str):
            payload[key] = date.fromisoformat(payload[key])
    for key in ("window_start", "window_end"):
        if isinstance(payload.get(key), str):
            payload[key] = datetime.fromisoformat(payload[key])
    return FetchWindowContract.model_validate(payload)


if __name__ == "__main__":
    main()
