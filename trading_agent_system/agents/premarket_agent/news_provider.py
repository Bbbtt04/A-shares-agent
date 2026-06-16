from __future__ import annotations

import json
import re
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Literal, TypeVar
from urllib.parse import urljoin, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from trading_agent_system.schemas import PremarketNewsItem, PremarketSourceStatus

CHINA_TZ = ZoneInfo("Asia/Shanghai")
T = TypeVar("T")
A_STOCK_DATA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass(frozen=True)
class FetchWindow:
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

    def filter_items(self, items: list[PremarketNewsItem]) -> list[PremarketNewsItem]:
        return [item for item in items if self.contains(item.published_at)]


def _filter_items_for_window(
    items: list[PremarketNewsItem],
    window: FetchWindow | None,
) -> list[PremarketNewsItem]:
    if window is None:
        return items
    return window.filter_items(items)


def _apply_limit(items: list[T], limit: int | None) -> list[T]:
    return items if limit is None else items[:limit]


def _request_size(limit: int | None, default: int = 100, maximum: int = 100) -> int:
    if limit is None:
        return min(default, maximum)
    return min(max(limit, default), maximum)


class NewsProviderResult:
    def __init__(
        self,
        source: str,
        items: list[PremarketNewsItem],
        status: str = "ok",
        error: str | None = None,
    ) -> None:
        self.source = source
        self.items = items
        self.status = status
        self.error = error

    def source_status(self, used_count: int) -> PremarketSourceStatus:
        return PremarketSourceStatus(
            source=self.source,
            provider_name=self.source,
            status=self.status,
            fetched_count=len(self.items),
            used_count=used_count,
            error=self.error,
        )


class CailianpressTelegraphProvider:
    source = "财联社电报"
    tier = "professional"
    url = "https://www.cls.cn/nodeapi/telegraphList"

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "lastTime": "",
            "os": "web",
            "rn": _request_size(limit),
        }
        try:
            payload = self._get(f"{self.url}?{urlencode(params)}")
            if payload.lstrip().startswith("<"):
                return NewsProviderResult(self.source, [], "failed", "财联社接口返回页面壳，未返回 JSON 电报列表")
            data = json.loads(payload)
            rows = data.get("data") or data.get("roll_data") or data.get("list") or []
            if isinstance(data.get("data"), dict):
                rows = data["data"].get("roll_data") or data["data"].get("list") or []
            items = [self._row_to_item(row) for row in _apply_limit(rows, limit) if isinstance(row, dict)]
            items = _filter_items_for_window([item for item in items if item.title], window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _get(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.cls.cn/telegraph",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        content = str(row.get("content") or row.get("brief") or row.get("title") or "")
        title = self._title_from_content(content)
        published_at = self._timestamp(row.get("ctime") or row.get("time") or row.get("modified_time"))
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=title,
            summary=self._clean_html(content),
            url=str(row.get("url") or row.get("shareurl") or "https://www.cls.cn/telegraph"),
            published_at=published_at,
            category="professional_wire",
            credibility=0.82,
        )

    def _title_from_content(self, content: str) -> str:
        clean = self._clean_html(content)
        match = re.search(r"【([^】]+)】", clean)
        if match:
            return match.group(1)
        return clean[:48]

    def _clean_html(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(value))).strip()

    def _timestamp(self, value: object) -> datetime | None:
        if value in (None, "", 0, "0"):
            return None
        number = int(float(value))
        if number > 10_000_000_000:
            number //= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)


class RssNewsProvider:
    def __init__(self, source: str, url: str, tier: str = "professional", timeout_seconds: int = 8) -> None:
        self.source = source
        self.url = url
        self.tier = tier
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        try:
            request = Request(self.url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,text/xml,*/*"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            root = ElementTree.fromstring(payload)
            rows = _apply_limit(root.findall(".//item"), limit)
            items = [self._item_to_news(row) for row in rows]
            items = _filter_items_for_window(items, window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _item_to_news(self, row: ElementTree.Element) -> PremarketNewsItem:
        title = self._text(row, "title")
        summary = self._text(row, "description")
        published_at = self._pub_date(self._text(row, "pubDate"))
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=title,
            summary=re.sub(r"<[^>]+>", "", unescape(summary)).strip(),
            url=self._text(row, "link") or None,
            published_at=published_at,
            category="rss",
            credibility=0.75 if self.tier == "professional" else 0.9 if self.tier == "official" else 0.45,
        )

    def _text(self, row: ElementTree.Element, tag: str) -> str:
        node = row.find(tag)
        return node.text.strip() if node is not None and node.text else ""

    def _pub_date(self, value: str) -> datetime | None:
        if not value:
            return None
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


class EastMoneyNewsProvider:
    source = "东方财富财经新闻"
    tier = "professional"
    url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"

    def __init__(self, column: str = "350", timeout_seconds: int = 8) -> None:
        self.column = column
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        params = {
            "client": "web",
            "biz": "web_news_col",
            "column": self.column,
            "pageSize": _request_size(limit),
            "page": 1,
            "req_trace": "premarket_agent",
        }
        try:
            request = Request(
                f"{self.url}?{urlencode(params)}",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
            )
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            data = json.loads(payload)
            rows = data.get("data", {}).get("list", []) if isinstance(data.get("data"), dict) else []
            items = [self._row_to_item(row) for row in _apply_limit(rows, limit) if isinstance(row, dict)]
            items = _filter_items_for_window([item for item in items if item.title], window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        return PremarketNewsItem(
            source=str(row.get("mediaName") or self.source),
            source_tier=self.tier,
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            url=str(row.get("uniqueUrl") or row.get("url") or ""),
            published_at=self._timestamp(str(row.get("showTime") or "")),
            category="eastmoney_news",
            credibility=0.76,
        )

    def _timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)


class SinaFinanceRollProvider:
    source = "新浪财经滚动"
    tier = "professional"
    url = "https://feed.mix.sina.com.cn/api/roll/get"

    def __init__(
        self,
        source: str = "新浪财经滚动",
        lid: str = "2516",
        category: str = "sina_finance",
        timeout_seconds: int = 8,
        max_pages: int = 20,
        page_size: int = 50,
    ) -> None:
        self.source = source
        self.lid = lid
        self.category = category
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.page_size = page_size

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        items: list[PremarketNewsItem] = []
        try:
            for page in range(1, self.max_pages + 1):
                rows = self._fetch_page(limit=limit, page=page)
                if not rows:
                    break
                page_items = [self._row_to_item(row) for row in rows if isinstance(row, dict)]
                items.extend(item for item in page_items if item.title)
                if self._page_is_older_than_window(page_items, window):
                    break
                if limit is not None and window is None and len(items) >= limit:
                    break
            items = _apply_limit(_filter_items_for_window(items, window), limit)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _fetch_page(self, limit: int | None, page: int) -> list[dict[str, object]]:
        params = {
            "pageid": "153",
            "lid": self.lid,
            "num": _request_size(limit, self.page_size),
            "page": str(page),
        }
        request = Request(
            f"{self.url}?{urlencode(params)}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="ignore")
        data = json.loads(payload)
        result = data.get("result", {}) if isinstance(data, dict) else {}
        status = result.get("status", {})
        if status.get("code") not in (0, "0"):
            raise RuntimeError(str(status.get("msg") or status))
        rows = result.get("data") or []
        return rows if isinstance(rows, list) else []

    def _page_is_older_than_window(self, items: list[PremarketNewsItem], window: FetchWindow | None) -> bool:
        if window is None:
            return False
        timestamps = [item.published_at.astimezone(ZoneInfo(window.timezone)) for item in items if item.published_at]
        return bool(timestamps) and max(timestamps) < window.window_start

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        title = str(row.get("title") or row.get("stitle") or "")
        intro = str(row.get("intro") or "")
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=title,
            summary=intro,
            url=str(row.get("url") or row.get("wapurl") or ""),
            published_at=self._timestamp(row.get("ctime") or row.get("intime")),
            category=self.category,
            credibility=0.72,
        )

    def _timestamp(self, value: object) -> datetime | None:
        if value in (None, "", 0, "0"):
            return None
        return datetime.fromtimestamp(int(float(value)), tz=timezone.utc)


class CsrcNewsProvider:
    source = "证监会要闻"
    tier = "official"
    url = "https://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml"
    api_url = "https://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8"

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        try:
            items = self._fetch_json(limit, window)
            if items:
                return NewsProviderResult(self.source, items, "ok")
            request = Request(self.url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            items = self._parse_items(payload, limit)
            items = _filter_items_for_window(items, window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _fetch_json(self, limit: int | None, window: FetchWindow | None = None) -> list[PremarketNewsItem]:
        params = {
            "_isAgg": "true",
            "_isJson": "true",
            "_pageSize": _request_size(limit),
            "_template": "index",
            "_rangeTimeGte": window.window_start.strftime("%Y-%m-%d") if window else "",
            "_channelName": "",
            "page": 1,
        }
        request = Request(
            f"{self.api_url}?{urlencode(params)}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="ignore")
        data = json.loads(payload)
        rows = data.get("data", {}).get("results", []) if isinstance(data.get("data"), dict) else []
        return _filter_items_for_window(
            [self._row_to_item(row) for row in _apply_limit(rows, limit) if isinstance(row, dict)],
            window,
        )

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        published = str(row.get("publishedTimeStr") or row.get("publishedTime") or "")
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=title,
            summary=title,
            url=urljoin("https://www.csrc.gov.cn", str(row.get("url") or "")),
            published_at=self._timestamp(published),
            category="official_policy",
            credibility=0.94,
        )

    def _timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        if len(value) >= 19:
            try:
                return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)
            except ValueError:
                pass
        if len(value) >= 10:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)
            except ValueError:
                pass
        return None

    def _parse_items(self, payload: str, limit: int | None) -> list[PremarketNewsItem]:
        rows = re.findall(
            r'<a[^>]+href="(?P<href>[^"]+)"[^>]*title="(?P<title>[^"]+)"[^>]*>.*?</a>.*?(?P<date>\d{4}-\d{2}-\d{2})',
            payload,
            flags=re.S,
        )
        if not rows:
            rows = re.findall(
                r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>[^<]{4,120})</a>\s*<span[^>]*>(?P<date>\d{4}-\d{2}-\d{2})</span>',
                payload,
                flags=re.S,
            )
        items = []
        for href, raw_title, raw_date in _apply_limit(rows, limit):
            title = re.sub(r"\s+", " ", unescape(raw_title)).strip()
            items.append(
                PremarketNewsItem(
                    source=self.source,
                    source_tier=self.tier,
                    title=title,
                    summary=title,
                    url=urljoin(self.url, href),
                    published_at=self._timestamp(raw_date),
                    category="official_policy",
                    credibility=0.94,
                )
            )
        return items


def _clean_text(value: object, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(str(value or "")))).strip()
    if max_length and len(text) > max_length:
        return f"{text[:max_length].rstrip()}..."
    return text


def _as_text(value: object) -> str:
    return str(value or "").strip()


def _timestamp_from_epoch(value: object) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number > 10_000_000_000:
        number //= 1000
    return datetime.fromtimestamp(number, tz=timezone.utc)


def _timestamp_from_text(value: object) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
    if len(text) >= 19:
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    if len(text) >= 10:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
            return parsed.replace(hour=16, tzinfo=CHINA_TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def _a_stock_code(symbol: object) -> str:
    text = _as_text(symbol).upper()
    if "." in text:
        text = text.split(".")[0]
    text = re.sub(r"^(SH|SZ|BJ)", "", text)
    match = re.search(r"\d{6}", text)
    return match.group(0) if match else ""


def _format_a_stock_symbol(symbol: object) -> str:
    code = _a_stock_code(symbol)
    if not code:
        return _as_text(symbol)
    if code.startswith(("5", "6", "9")):
        market = "SH"
    elif code.startswith(("4", "8")):
        market = "BJ"
    else:
        market = "SZ"
    return f"{code}.{market}"


class KaipanlaNewsProvider:
    source = "开盘啦最新资讯"
    tier = "sentiment"
    url = "https://www.kaipanla.com/latest-news/1"

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        try:
            payload = self._get(self.url)
            rows = self._extract_rows(payload)
            items = [self._row_to_item(row) for row in _apply_limit(rows, limit)]
            items = [item for item in items if item.title]
            items = _filter_items_for_window(items, window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _get(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _extract_rows(self, payload: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()

        def add(row: dict[str, object]) -> None:
            title = _clean_text(row.get("Title") or row.get("title"))
            if not title:
                return
            key = str(row.get("ID") or row.get("id") or title)
            if key in seen:
                return
            seen.add(key)
            rows.append(row)

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key in ("Latest", "Flash", "List", "list", "items"):
                    nested = value.get(key)
                    if isinstance(nested, list):
                        for row in nested:
                            if isinstance(row, dict) and (row.get("Title") or row.get("title")):
                                add(row)
                for nested in value.values():
                    walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)
                return
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        walk(json.loads(stripped))
                    except json.JSONDecodeError:
                        return

        for match in re.findall(r'<script[^>]+data-nuxt-data="[^"]+"[^>]*>(.*?)</script>', payload, flags=re.S):
            try:
                walk(json.loads(unescape(match)))
            except json.JSONDecodeError:
                continue
        if not rows:
            html_rows = re.findall(r'href="/article/(?P<id>\d+)"[^>]*class="item-link"[^>]*>(?P<title>[^<]+)</a>', payload)
            for article_id, title in html_rows:
                add({"ID": article_id, "Title": title})
        return rows

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        article_id = str(row.get("ID") or row.get("id") or "")
        title = _clean_text(row.get("Title") or row.get("title"))
        summary = _clean_text(row.get("ZhaiYao") or row.get("summary") or title)
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=title,
            summary=summary,
            url=f"https://www.kaipanla.com/article/{article_id}" if article_id else self.url,
            published_at=_timestamp_from_epoch(row.get("CreateTime") or row.get("create_time")),
            category="platform_news",
            credibility=0.46,
            risk_flags=["third_party_platform", "sentiment_only"],
        )


class XueqiuHotProvider:
    source = "雪球热议"
    tier = "sentiment"
    url = "https://xueqiu.com/statuses/hot/listV2.json"

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        try:
            payload = self._get_json(
                f"{self.url}?{urlencode({'since_id': -1, 'max_id': -1, 'size': _request_size(limit)})}"
            )
            if isinstance(payload, dict) and payload.get("error_code"):
                return NewsProviderResult(
                    self.source,
                    [],
                    "failed",
                    f"{payload.get('error_code')}: {payload.get('error_description') or payload.get('error_uri')}",
                )
            rows = self._extract_rows(payload)
            items = [self._row_to_item(row) for row in _apply_limit(rows, limit)]
            items = [item for item in items if item.title]
            items = _filter_items_for_window(items, window)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _get_json(self, url: str) -> object:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://xueqiu.com/",
        }
        request = Request(url, headers=headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="ignore")
        return json.loads(payload)

    def _extract_rows(self, payload: object) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                row = value.get("status") or value.get("original_status")
                if isinstance(row, dict) and (row.get("text") or row.get("description") or row.get("title")):
                    rows.append(row)
                elif value.get("text") or value.get("description") or value.get("title"):
                    rows.append(value)
                for key in ("items", "list", "statuses", "data"):
                    nested = value.get(key)
                    if isinstance(nested, (list, dict)):
                        walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(payload)
        return rows

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        text = _clean_text(row.get("text") or row.get("description") or row.get("title"), max_length=280)
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        user_name = str(user.get("screen_name") or user.get("name") or "雪球用户") if isinstance(user, dict) else "雪球用户"
        row_id = row.get("id") or row.get("status_id")
        user_id = user.get("id") if isinstance(user, dict) else None
        url = str(row.get("target") or row.get("url") or "")
        if not url and user_id and row_id:
            url = f"https://xueqiu.com/{user_id}/{row_id}"
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=text[:80],
            summary=f"{user_name}: {text}",
            url=url or "https://xueqiu.com",
            published_at=_timestamp_from_epoch(row.get("created_at") or row.get("time")),
            category="social_discussion",
            credibility=0.36,
            risk_flags=["third_party_platform", "sentiment_only"],
        )


class TonghuashunNewsProvider:
    source = "同花顺7x24"
    tier = "professional"
    url = "https://news.10jqka.com.cn/tapp/news/push/stock/"

    def __init__(self, timeout_seconds: int = 8, max_pages: int = 20, page_size: int = 50) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.page_size = page_size

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        items: list[PremarketNewsItem] = []
        try:
            for page in range(1, self.max_pages + 1):
                rows = self._fetch_page(page=page, limit=limit)
                if not rows:
                    break
                page_items = [self._row_to_item(row) for row in rows if isinstance(row, dict)]
                items.extend(item for item in page_items if item.title)
                if self._page_is_older_than_window(page_items, window):
                    break
                if limit is not None and window is None and len(items) >= limit:
                    break
            items = _apply_limit(_filter_items_for_window(items, window), limit)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _fetch_page(self, page: int, limit: int | None) -> list[dict[str, object]]:
        params = {
            "page": page,
            "tag": "",
            "track": "website",
            "pagesize": _request_size(limit, self.page_size),
        }
        request = Request(
            f"{self.url}?{urlencode(params)}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://news.10jqka.com.cn/realtimenews.html",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="ignore")
        data = json.loads(payload)
        if str(data.get("code")) != "200":
            raise RuntimeError(str(data.get("msg") or data))
        rows = data.get("data", {}).get("list", []) if isinstance(data.get("data"), dict) else []
        return rows if isinstance(rows, list) else []

    def _page_is_older_than_window(self, items: list[PremarketNewsItem], window: FetchWindow | None) -> bool:
        if window is None:
            return False
        timestamps = [item.published_at.astimezone(ZoneInfo(window.timezone)) for item in items if item.published_at]
        return bool(timestamps) and max(timestamps) < window.window_start

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        return PremarketNewsItem(
            source=self.source,
            source_tier=self.tier,
            title=_clean_text(row.get("title")),
            summary=_clean_text(row.get("digest") or row.get("short") or row.get("title"), max_length=320),
            url=str(row.get("url") or row.get("shareUrl") or row.get("appUrl") or self.url),
            published_at=_timestamp_from_epoch(row.get("ctime") or row.get("rtime")),
            category="ths_7x24",
            symbols=self._symbols(row.get("stock")),
            sectors=self._tag_names(row.get("tags")),
            credibility=0.7,
            risk_flags=["third_party_platform"],
        )

    def _tag_names(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        names = []
        for item in value:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return names

    def _symbols(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        symbols = []
        for item in value:
            if isinstance(item, dict) and item.get("code"):
                symbols.append(str(item["code"]))
        return symbols


class AStockDataPremarketProvider:
    source = "a-stock-data/premarket"

    def __init__(
        self,
        hotspot_fetcher=None,
        stock_news_fetcher=None,
        announcement_fetcher=None,
        quote_candidate_fetcher=None,
        symbols: list[str] | None = None,
        theme_symbols: dict[str, list[str]] | None = None,
        stock_data_adapter=None,
        timeout_seconds: int = 10,
        eastmoney_delay_seconds: float = 1.0,
        stock_news_page_size: int = 50,
        announcement_page_size: int = 30,
        quote_candidates_per_theme: int = 3,
    ) -> None:
        self.hotspot_fetcher = hotspot_fetcher or self._fetch_hotspots
        self.stock_news_fetcher = stock_news_fetcher or self._fetch_stock_news
        self.announcement_fetcher = announcement_fetcher or self._fetch_announcements
        self.quote_candidate_fetcher = quote_candidate_fetcher or self._fetch_quote_candidates
        self.symbols = symbols or []
        self.theme_symbols = theme_symbols or {}
        self.stock_data_adapter = stock_data_adapter
        self.timeout_seconds = timeout_seconds
        self.eastmoney_delay_seconds = eastmoney_delay_seconds
        self.stock_news_page_size = stock_news_page_size
        self.announcement_page_size = announcement_page_size
        self.quote_candidates_per_theme = quote_candidates_per_theme
        self._last_eastmoney_call = 0.0
        self._current_window: FetchWindow | None = None
        self._current_trading_day: date | None = None
        self._cninfo_orgid_map: dict[str, str] = {}

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        previous_window = self._current_window
        previous_trading_day = self._current_trading_day
        self._current_window = window
        self._current_trading_day = window.trading_day if window else date.today()
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
        finally:
            self._current_window = previous_window
            self._current_trading_day = previous_trading_day

    def _tag_rows(
        self,
        rows: list[dict[str, object]] | None,
        category: str,
        source_tier: str,
        credibility: float,
    ) -> list[dict[str, object]]:
        tagged = []
        for row in rows or []:
            item = dict(row)
            item["category"] = category
            item["source_tier"] = source_tier
            item["credibility"] = credibility
            tagged.append(item)
        return tagged

    def _row_to_item(self, row: dict[str, object]) -> PremarketNewsItem:
        symbol = _as_text(row.get("symbol"))
        theme = _as_text(row.get("theme"))
        published_at = row.get("published_at")
        return PremarketNewsItem(
            source=self.source,
            provider_name="a-stock-data",
            source_tier=_as_text(row.get("source_tier")) or "professional",
            title=_as_text(row.get("title")),
            summary=_as_text(row.get("summary")),
            url=_as_text(row.get("url")) or None,
            published_at=published_at if isinstance(published_at, datetime) else None,
            category=_as_text(row.get("category")) or "unknown",
            symbols=[symbol] if symbol else [],
            sectors=[theme] if theme else [],
            credibility=float(row.get("credibility") or 0.6),
        )

    def _fetch_hotspots(self, limit: int | None = None) -> list[dict[str, object]]:
        trading_day = self._current_trading_day or date.today()
        url = (
            "http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{trading_day.isoformat()}/orderby/date/orderway/desc/charset/GBK/"
        )
        payload = self._get_text(url, headers={"User-Agent": A_STOCK_DATA_UA}, encoding="gbk")
        data = json.loads(payload)
        if data.get("errocode", 0) != 0:
            raise RuntimeError(str(data.get("errormsg") or data))
        rows: list[dict[str, object]] = []
        allowed_symbols = set(self.symbols)
        max_rows = limit or 100
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            symbol = _format_a_stock_symbol(row.get("code"))
            if allowed_symbols and symbol not in allowed_symbols:
                continue
            reason = _clean_text(row.get("reason"))
            theme = self._theme_from_reason(reason)
            rows.append(
                {
                    "title": f"{_clean_text(row.get('name'))}({symbol}) 同花顺强势股",
                    "summary": f"题材归因：{reason or '-'}；涨幅：{_as_text(row.get('zhangfu')) or '-'}。",
                    "symbol": symbol,
                    "theme": theme,
                    "published_at": self._synthetic_published_at(),
                }
            )
            if len(rows) >= max_rows:
                break
        return rows

    def _fetch_stock_news(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        page_size = limit or self.stock_news_page_size
        for symbol in symbols:
            code = _a_stock_code(symbol)
            if not code:
                continue
            self._throttle_eastmoney()
            payload = self._get_text(
                "https://search-api-web.eastmoney.com/search/jsonp",
                params={
                    "cb": "jQuery_news",
                    "param": json.dumps(
                        {
                            "uid": "",
                            "keyword": code,
                            "type": ["cmsArticleWebOld"],
                            "client": "web",
                            "clientType": "web",
                            "clientVersion": "curr",
                            "param": {
                                "cmsArticleWebOld": {
                                    "searchScope": "default",
                                    "sort": "default",
                                    "pageIndex": 1,
                                    "pageSize": page_size,
                                    "preTag": "",
                                    "postTag": "",
                                }
                            },
                        },
                        separators=(",", ":"),
                    ),
                },
                headers={"User-Agent": A_STOCK_DATA_UA, "Referer": "https://so.eastmoney.com/"},
            )
            data = self._parse_jsonp(payload)
            articles = data.get("result", {}).get("cmsArticleWebOld", []) if isinstance(data.get("result"), dict) else []
            for article in articles or []:
                if not isinstance(article, dict):
                    continue
                rows.append(
                    {
                        "title": _clean_text(article.get("title")),
                        "summary": _clean_text(article.get("content"), max_length=240),
                        "symbol": symbol,
                        "theme": self._theme_for_symbol(symbol),
                        "url": _as_text(article.get("url")),
                        "published_at": _timestamp_from_text(article.get("date")),
                    }
                )
                if limit is not None and len(rows) >= limit:
                    return rows
        return rows

    def _fetch_announcements(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        page_size = limit or self.announcement_page_size
        for symbol in symbols:
            code = _a_stock_code(symbol)
            if not code:
                continue
            data = self._post_form_json(
                "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                data={
                    "stock": f"{code},{self._cninfo_orgid(code)}",
                    "tabName": "fulltext",
                    "pageSize": str(page_size),
                    "pageNum": "1",
                    "column": "",
                    "category": "",
                    "plate": "",
                    "seDate": "",
                    "searchkey": "",
                    "secid": "",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                },
                headers={
                    "User-Agent": A_STOCK_DATA_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://www.cninfo.com.cn/new/disclosure",
                    "Origin": "https://www.cninfo.com.cn",
                },
            )
            for item in data.get("announcements", []) or []:
                if not isinstance(item, dict):
                    continue
                announcement_id = _as_text(item.get("announcementId"))
                rows.append(
                    {
                        "title": _clean_text(item.get("announcementTitle")),
                        "summary": _clean_text(item.get("announcementTypeName")),
                        "symbol": symbol,
                        "theme": self._theme_for_symbol(symbol),
                        "url": (
                            f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={announcement_id}"
                            if announcement_id
                            else "https://www.cninfo.com.cn/new/disclosure"
                        ),
                        "published_at": _timestamp_from_epoch(item.get("announcementTime"))
                        or _timestamp_from_text(item.get("date")),
                    }
                )
                if limit is not None and len(rows) >= limit:
                    return rows
        return rows

    def _fetch_quote_candidates(self, symbols: list[str], limit: int | None = None) -> list[dict[str, object]]:
        if self.stock_data_adapter is None:
            return []
        rows: list[dict[str, object]] = []
        max_rows = limit
        symbol_set = set(symbols)
        for theme, theme_symbols in self.theme_symbols.items():
            if symbol_set and not symbol_set.intersection(theme_symbols):
                continue
            for candidate in self.stock_data_adapter.candidates_for_theme(theme, limit=self.quote_candidates_per_theme):
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
                        "published_at": self._synthetic_published_at(),
                    }
                )
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
        return rows

    def _theme_from_reason(self, reason: str) -> str | None:
        for theme in self.theme_symbols:
            if theme in reason:
                return theme
        for separator in ("+", "，", ",", "/", " "):
            if separator in reason:
                return reason.split(separator)[0].strip() or None
        return reason or None

    def _theme_for_symbol(self, symbol: str) -> str | None:
        for theme, symbols in self.theme_symbols.items():
            if symbol in symbols:
                return theme
        return None

    def _synthetic_published_at(self) -> datetime:
        if self._current_window is not None:
            return (self._current_window.window_end - timedelta(minutes=1)).astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _get_text(
        self,
        url: str,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        target = f"{url}?{urlencode(params)}" if params else url
        request = Request(target, headers=headers or {"User-Agent": A_STOCK_DATA_UA})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode(encoding, errors="ignore")

    def _post_form_json(self, url: str, data: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
        request = Request(url, data=urlencode(data).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))

    def _parse_jsonp(self, payload: str) -> dict[str, object]:
        start = payload.find("(")
        end = payload.rfind(")")
        if start >= 0 and end > start:
            payload = payload[start + 1 : end]
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}

    def _cninfo_orgid(self, code: str) -> str:
        if not self._cninfo_orgid_map:
            try:
                data = json.loads(
                    self._get_text(
                        "http://www.cninfo.com.cn/new/data/szse_stock.json",
                        headers={"User-Agent": A_STOCK_DATA_UA},
                    )
                )
                self._cninfo_orgid_map = {
                    str(item["code"]): str(item["orgId"])
                    for item in data.get("stockList", [])
                    if isinstance(item, dict) and item.get("code") and item.get("orgId")
                }
            except Exception:
                self._cninfo_orgid_map = {}
        org_id = self._cninfo_orgid_map.get(code)
        if org_id:
            return org_id
        if code.startswith("6"):
            return f"gssh0{code}"
        if code.startswith(("8", "4")):
            return f"gsbj0{code}"
        return f"gssz0{code}"

    def _throttle_eastmoney(self) -> None:
        if self._last_eastmoney_call:
            wait = self.eastmoney_delay_seconds - (time_module.time() - self._last_eastmoney_call)
            if wait > 0:
                time_module.sleep(wait)
        self._last_eastmoney_call = time_module.time()


class DemoPremarketNewsProvider:
    source = "demo"

    def fetch(self, limit: int | None = None, window: FetchWindow | None = None) -> NewsProviderResult:
        now = datetime.now(timezone.utc)
        items = [
            PremarketNewsItem(
                source="证监会/交易所公告 demo",
                source_tier="official",
                title="监管层释放支持并购重组与科技企业融资信号",
                summary="政策导向利好科技成长与券商投行链条，需等待正式文件和交易所细则确认。",
                published_at=now,
                category="official_policy",
                sectors=["半导体", "券商"],
                credibility=0.92,
            ),
            PremarketNewsItem(
                source="财联社 demo",
                source_tier="professional",
                title="多家机器人产业链公司披露订单增长",
                summary="机器人主题盘前热度提升，但若集合竞价高开过大，应只观察不追。",
                published_at=now,
                category="industry_catalyst",
                sectors=["机器人"],
                symbols=["300124.SZ"],
                credibility=0.78,
            ),
            PremarketNewsItem(
                source="雪球 demo",
                source_tier="sentiment",
                title="热门讨论集中在低空经济与算力方向",
                summary="情绪线索升温，不能单独作为交易依据。",
                published_at=now,
                category="sentiment",
                sectors=["低空经济", "算力"],
                credibility=0.38,
                risk_flags=["sentiment_only"],
            ),
        ]
        items = _filter_items_for_window(_apply_limit(items, limit), window)
        return NewsProviderResult(self.source, items, "ok" if items else "empty")
