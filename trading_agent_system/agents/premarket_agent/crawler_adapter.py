from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

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


class McpToolClientProtocol(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
        return _response_to_result(self, response)


class McpPremarketCrawlerProvider:
    source = "premarket-crawler-mcp"

    def __init__(
        self,
        client: McpToolClientProtocol,
        sources: list[str] | None = None,
        fallback_provider: object | None = None,
        source: str | None = None,
    ) -> None:
        self.client = client
        self.sources = sources or []
        self.fallback_provider = fallback_provider
        if source:
            self.source = source
        self.last_response: CrawlerResponseContract | None = None
        self.last_source_status: list[PremarketSourceStatus] = []

    def fetch(self, limit: int = 30, window: object | None = None) -> NewsProviderResult:
        if window is None:
            raise ValueError("crawler adapter requires a fetch window")
        contract_window = _to_contract_window(window)
        try:
            payload = self.client.call_tool(
                "fetch_premarket_news",
                {
                    "sources": self.sources,
                    "limit_per_source": limit,
                    "window": contract_window.model_dump(mode="json"),
                },
            )
        except Exception:
            if self.fallback_provider is None:
                raise
            return self.fallback_provider.fetch(limit=limit, window=window)
        response = CrawlerResponseContract.model_validate(payload)
        return _response_to_result(self, response)


class StdioMcpToolClient:
    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env
        self.timeout_seconds = timeout_seconds

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import anyio

        return anyio.run(self._call_tool, name, arguments)

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            cwd=self.cwd,
            env=self.env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
            ) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(_tool_error_text(result))
        if result.structuredContent is not None:
            return dict(result.structuredContent)
        return _tool_content_to_dict(result.content)


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


def _response_to_result(
    provider: LocalPremarketCrawlerProvider | McpPremarketCrawlerProvider,
    response: CrawlerResponseContract,
) -> NewsProviderResult:
    provider.last_response = response
    provider.last_source_status = [
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
    return NewsProviderResult(provider.source, items, status, error)


def _tool_content_to_dict(content: list[object]) -> dict[str, Any]:
    if not content:
        raise RuntimeError("MCP tool returned no content")
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        raise RuntimeError("MCP tool returned non-text content without structuredContent")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError("MCP tool returned JSON that is not an object")
    return parsed


def _tool_error_text(result: object) -> str:
    content = getattr(result, "content", [])
    if content:
        text = getattr(content[0], "text", None)
        if text:
            return str(text)
    return "MCP tool call failed"
