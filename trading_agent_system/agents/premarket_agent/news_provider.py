from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from trading_agent_system.schemas import PremarketNewsItem, PremarketSourceStatus

CHINA_TZ = ZoneInfo("Asia/Shanghai")


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

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "lastTime": "",
            "os": "web",
            "rn": limit,
        }
        try:
            payload = self._get(f"{self.url}?{urlencode(params)}")
            if payload.lstrip().startswith("<"):
                return NewsProviderResult(self.source, [], "failed", "财联社接口返回页面壳，未返回 JSON 电报列表")
            data = json.loads(payload)
            rows = data.get("data") or data.get("roll_data") or data.get("list") or []
            if isinstance(data.get("data"), dict):
                rows = data["data"].get("roll_data") or data["data"].get("list") or []
            items = [self._row_to_item(row) for row in rows[:limit] if isinstance(row, dict)]
            return NewsProviderResult(self.source, [item for item in items if item.title], "ok" if items else "empty")
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

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        try:
            request = Request(self.url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml,text/xml,*/*"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            root = ElementTree.fromstring(payload)
            rows = root.findall(".//item")[:limit]
            items = [self._item_to_news(row) for row in rows]
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

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        params = {
            "client": "web",
            "biz": "web_news_col",
            "column": self.column,
            "pageSize": limit,
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
            items = [self._row_to_item(row) for row in rows[:limit] if isinstance(row, dict)]
            return NewsProviderResult(self.source, [item for item in items if item.title], "ok" if items else "empty")
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

    def __init__(self, lid: str = "2515", timeout_seconds: int = 8) -> None:
        self.lid = lid
        self.timeout_seconds = timeout_seconds

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        params = {
            "pageid": "153",
            "lid": self.lid,
            "num": limit,
            "page": "1",
        }
        try:
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
                return NewsProviderResult(self.source, [], "failed", str(status.get("msg") or status))
            rows = result.get("data") or []
            items = [self._row_to_item(row) for row in rows[:limit] if isinstance(row, dict)]
            return NewsProviderResult(self.source, [item for item in items if item.title], "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

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
            category="sina_roll",
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

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        try:
            items = self._fetch_json(limit)
            if items:
                return NewsProviderResult(self.source, items, "ok")
            request = Request(self.url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            items = self._parse_items(payload, limit)
            return NewsProviderResult(self.source, items, "ok" if items else "empty")
        except Exception as error:
            return NewsProviderResult(self.source, [], "failed", str(error))

    def _fetch_json(self, limit: int) -> list[PremarketNewsItem]:
        params = {
            "_isAgg": "true",
            "_isJson": "true",
            "_pageSize": limit,
            "_template": "index",
            "_rangeTimeGte": "",
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
        return [self._row_to_item(row) for row in rows[:limit] if isinstance(row, dict)]

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

    def _parse_items(self, payload: str, limit: int) -> list[PremarketNewsItem]:
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
        for href, raw_title, raw_date in rows[:limit]:
            title = re.sub(r"\s+", " ", unescape(raw_title)).strip()
            items.append(
                PremarketNewsItem(
                    source=self.source,
                    source_tier=self.tier,
                    title=title,
                    summary=title,
                    url=urljoin(self.url, href),
                    published_at=None,
                    category="official_policy",
                    credibility=0.94,
                )
            )
        return items


class DemoPremarketNewsProvider:
    source = "demo"

    def fetch(self, limit: int = 30) -> NewsProviderResult:
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
        return NewsProviderResult(self.source, items[:limit], "ok")
