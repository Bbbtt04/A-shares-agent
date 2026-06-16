from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"
API = ROOT / "web" / "src" / "api.js"
CSS = ROOT / "web" / "src" / "styles.css"


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


def test_source_detail_rows_have_readable_text_layout():
    source = MAIN.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "debug-source-item-title" in source
    assert "debug-source-item-summary" in source
    assert "debug-source-item-meta" in source
    assert ".debug-source-item-title" in css
    assert ".debug-source-item-summary" in css
    assert ".debug-source-item-meta" in css


def test_crawled_documents_step_can_show_fetch_window():
    source = MAIN.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "debug-step-window" in source
    assert "metadata?.window_start" in source
    assert ".debug-step-window" in css


def test_premarket_debug_page_shows_a_stock_data_summary():
    source = MAIN.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "aStockData" in source
    assert "a-stock-data 数据包" in source
    assert "category_counts" in source
    assert "同花顺热点" in source
    assert "盘前观察候选" in source
    assert "debug-a-stock-data-grid" in source
    assert ".debug-a-stock-data-grid" in css
