from __future__ import annotations

import json
from datetime import date

from trading_agent_system.api import app as api_module
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.knowledge import KnowledgeRecord, KnowledgeStore
from trading_agent_system.core.storage import JsonlEventRepository


def test_premarket_debug_api_returns_chain_from_events_knowledge_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    monkeypatch.setattr(api_module, "KNOWLEDGE_PATH", tmp_path / "knowledge.sqlite")
    monkeypatch.setattr(api_module, "PREMARKET_REPORT_DIR", tmp_path / "reports" / "premarket")
    api_module.PREMARKET_REPORT_DIR.mkdir(parents=True)

    repository = JsonlEventRepository(api_module.EVENT_DIR)
    trading_day = date(2026, 6, 10)
    repository.append_envelope(
        make_envelope(
            "premarket.raw_documents",
            [{"source_id": "src_1", "title": "机器人政策新闻", "source_name": "新浪财经"}],
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_1",
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.normalized_events",
            [{"event_id": "evt_1", "title": "机器人政策催化", "related_themes": ["机器人"]}],
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_1",
            evidence_ids=["src_1"],
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.event_clusters",
            [{"cluster_id": "cluster_1", "title": "机器人: 政策催化", "primary_event_id": "evt_1"}],
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_1",
            evidence_ids=["evt_1"],
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.rag_evidence_packs",
            {
                "pack_count": 1,
                "packs": [{"section": "theme_candidates", "items": [{"evidence_id": "evt_1", "title": "机器人政策催化"}]}],
            },
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_1",
            evidence_ids=["evt_1"],
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.rag_evaluation",
            {"summary": {"avg_evidence_coverage_ratio": 1.0}},
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_1",
            evidence_ids=["evt_1"],
        )
    )

    KnowledgeStore(api_module.KNOWLEDGE_PATH).upsert(
        KnowledgeRecord(
            record_id="rec_robot",
            record_type="event",
            trading_day=trading_day,
            source="新浪财经",
            source_rank="authorized_news",
            title="机器人政策催化",
            summary="机器人政策进入盘前知识库。",
            content="机器人 政策",
            themes=["机器人"],
            event_ids=["evt_1"],
            evidence_ids=["src_1"],
            confidence=0.9,
        )
    )
    (api_module.PREMARKET_REPORT_DIR / "2026-06-10.json").write_text(
        json.dumps(
            {
                "date": "2026-06-10",
                "market_view": "neutral",
                "summary": "盘前关注机器人。",
                "watchlist": [{"symbol": "002747.SZ", "reason": "机器人政策催化"}],
                "avoid_list": [],
                "catalysts": [{"title": "机器人政策催化", "importance": "A"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = api_module.premarket_debug(trading_day=trading_day, q="机器人")

    assert response["trading_day"] == "2026-06-10"
    assert response["conclusion"]["summary"] == "盘前关注机器人。"
    raw_documents = next(step for step in response["steps"] if step["id"] == "raw_documents")
    assert raw_documents["count"] == 1
    assert response["knowledge"]["query_results"][0]["record"]["record_id"] == "rec_robot"
    assert response["rag"]["evidence"]["payload"]["pack_count"] == 1
    assert response["rag"]["evaluation"]["payload"]["summary"]["avg_evidence_coverage_ratio"] == 1.0


def test_premarket_debug_api_separates_source_fetch_from_window_filtered_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    monkeypatch.setattr(api_module, "KNOWLEDGE_PATH", tmp_path / "knowledge.sqlite")
    monkeypatch.setattr(api_module, "PREMARKET_REPORT_DIR", tmp_path / "reports" / "premarket")
    api_module.PREMARKET_REPORT_DIR.mkdir(parents=True)

    repository = JsonlEventRepository(api_module.EVENT_DIR)
    trading_day = date(2026, 6, 12)
    repository.append_envelope(
        make_envelope(
            "premarket.crawled_documents",
            {
                "total_count": 2,
                "window_start": "2026-06-11T15:00:00+08:00",
                "window_end": "2026-06-12T09:30:00+08:00",
                "items": [
                    {"item_id": "crawl_1", "source": "东方财富财经新闻", "title": "窗口外消息", "in_premarket_window": False},
                    {"item_id": "crawl_2", "source": "新浪财经滚动", "title": "窗口外消息二", "in_premarket_window": False},
                ],
            },
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_empty",
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.raw_documents",
            [],
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_empty",
        )
    )
    (api_module.PREMARKET_REPORT_DIR / "2026-06-12.json").write_text(
        json.dumps(
            {
                "date": "2026-06-12",
                "market_view": "cautious",
                "summary": "盘前消息源质量不足。",
                "source_status": [
                    {"source": "东方财富财经新闻", "status": "ok", "fetched_count": 10, "used_count": 0},
                    {"source": "新浪财经滚动", "status": "ok", "fetched_count": 30, "used_count": 0},
                ],
                "warnings": ["盘前窗口内没有可用消息，禁止基于新闻做主动买入。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = api_module.premarket_debug(trading_day=trading_day, q="盘前")

    source_fetch = response["steps"][0]
    crawled_documents = response["steps"][1]
    raw_documents = response["steps"][2]
    assert source_fetch["id"] == "source_fetch"
    assert source_fetch["label"] == "源站抓取状态"
    assert source_fetch["count"] == 40
    assert source_fetch["items"][0]["source"] == "东方财富财经新闻"
    assert crawled_documents["id"] == "crawled_documents"
    assert crawled_documents["label"] == "全部爬取数据"
    assert crawled_documents["count"] == 2
    assert crawled_documents["metadata"]["window_start"] == "2026-06-11T15:00:00+08:00"
    assert crawled_documents["metadata"]["window_end"] == "2026-06-12T09:30:00+08:00"
    assert [item["title"] for item in crawled_documents["items"]] == ["窗口外消息", "窗口外消息二"]
    assert raw_documents["id"] == "raw_documents"
    assert raw_documents["label"] == "窗口内原始文档"
    assert raw_documents["status"] == "empty"
    assert raw_documents["count"] == 0
    assert raw_documents["items"] == []
    assert "盘前窗口内没有可用消息" in response["warnings"][0]


def test_premarket_debug_api_returns_a_stock_data_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    monkeypatch.setattr(api_module, "KNOWLEDGE_PATH", tmp_path / "knowledge.sqlite")
    monkeypatch.setattr(api_module, "PREMARKET_REPORT_DIR", tmp_path / "reports" / "premarket")
    config_path = tmp_path / "app.yaml"
    monkeypatch.setattr(api_module, "APP_CONFIG", config_path)
    api_module.PREMARKET_REPORT_DIR.mkdir(parents=True)
    config_path.write_text(
        """
premarket:
  a_stock_data:
    enabled: true
    symbols:
      - 688981.SH
      - 002371.SZ
""".strip(),
        encoding="utf-8",
    )

    repository = JsonlEventRepository(api_module.EVENT_DIR)
    trading_day = date(2026, 6, 13)
    repository.append_envelope(
        make_envelope(
            "premarket.crawled_documents",
            {
                "items": [
                    {
                        "source": "a-stock-data/premarket",
                        "provider_name": "a-stock-data/premarket",
                        "title": "中芯国际 同花顺强势股",
                        "category": "theme_hotspot",
                        "in_premarket_window": True,
                    },
                    {
                        "source": "a-stock-data/premarket",
                        "provider_name": "a-stock-data/premarket",
                        "title": "中芯国际 盘前观察候选",
                        "category": "quote_candidate",
                        "in_premarket_window": True,
                    },
                    {
                        "source": "同花顺7x24",
                        "title": "其它来源",
                        "category": "ths_7x24",
                        "in_premarket_window": True,
                    },
                ]
            },
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="run_a_stock_data",
        )
    )
    (api_module.PREMARKET_REPORT_DIR / "2026-06-13.json").write_text(
        json.dumps(
            {
                "date": "2026-06-13",
                "market_view": "neutral",
                "summary": "盘前关注半导体。",
                "source_status": [
                    {
                        "source": "a-stock-data/premarket",
                        "provider_name": "a-stock-data/premarket",
                        "status": "ok",
                        "fetched_count": 4,
                        "used_count": 2,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = api_module.premarket_debug(trading_day=trading_day, q="半导体")

    assert response["a_stock_data"] == {
        "enabled": True,
        "symbols": ["688981.SH", "002371.SZ"],
        "status": "ok",
        "fetched_count": 4,
        "used_count": 2,
        "crawled_count": 2,
        "in_window_count": 2,
        "category_counts": {"theme_hotspot": 1, "quote_candidate": 1},
    }
