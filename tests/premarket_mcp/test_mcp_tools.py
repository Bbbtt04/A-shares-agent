from premarket_crawler_mcp.server import health, list_sources


def test_health_tool_returns_service_identity():
    assert health()["service"] == "premarket-crawler-mcp"
    assert health()["status"] == "ok"


def test_list_sources_tool_exposes_tonghuashun():
    names = {source["name"] for source in list_sources()["sources"]}
    assert "tonghuashun" in names
