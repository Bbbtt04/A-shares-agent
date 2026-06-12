from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"
API = ROOT / "web" / "src" / "api.js"


def test_premarket_debug_tab_is_available():
    source = MAIN.read_text(encoding="utf-8")

    assert "盘前调试" in source
    assert "PremarketDebugPage" in source
    assert "源站抓取状态" in source
    assert "全部爬取数据" in source
    assert "窗口内原始文档" in source
    assert "落入知识库" in source
    assert "RAG 证据包" in source
    assert "最终结论" in source


def test_premarket_debug_api_client_exists():
    source = API.read_text(encoding="utf-8")

    assert "fetchPremarketDebug" in source
    assert "/api/premarket/debug" in source


def test_premarket_debug_records_are_not_hard_limited_to_ten_items():
    source = MAIN.read_text(encoding="utf-8")

    assert "currentStep.items.slice(0, 10)" not in source


def test_source_fetch_records_can_expand_to_crawled_items():
    source = MAIN.read_text(encoding="utf-8")

    assert "expandedSourceKeys" in source
    assert "crawledItemsBySource" in source
    assert "debugSourceKey" in source
    assert "provider_name" in source
    assert "debug-source-toggle" in source
    assert "debug-source-items" in source
