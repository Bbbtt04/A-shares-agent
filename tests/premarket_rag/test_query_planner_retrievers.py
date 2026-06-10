from datetime import date

from trading_agent_system.agents.premarket_agent.rag.query_planner import PreMarketRAGQueryPlanner
from trading_agent_system.agents.premarket_agent.rag.retrievers.risk_event_retriever import RiskEventRetriever
from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument


def test_query_planner_splits_by_morning_sections():
    planner = PreMarketRAGQueryPlanner()

    tasks = planner.build_tasks(trading_day=date(2026, 6, 10), premarket_window_id="pmw_20260610")

    sections = {task.section for task in tasks}
    assert "core_conclusion" in sections
    assert "portfolio_risks" in sections
    assert "theme_candidates" in sections
    assert len(tasks) >= 5


def test_risk_event_retriever_finds_risk_without_vector_search():
    document = RAGDocument(
        doc_id="doc_risk",
        title="收到监管函",
        content="公司收到监管函",
        content_type="event_card",
        source="上交所",
        source_type="exchange_notice",
        source_rank=1.0,
        fetched_at="2026-06-10T00:00:00Z",
        trading_day=date(2026, 6, 10),
        premarket_window_id="pmw_20260610",
        symbols=["600000.SH"],
        risk_flags=["regulatory_inquiry"],
        content_hash="hash_risk",
    )
    retriever = RiskEventRetriever([document])
    task = PreMarketRAGQueryPlanner().build_tasks(date(2026, 6, 10), "pmw_20260610")[0]

    results = retriever.retrieve(task)

    assert results[0].doc_id == "doc_risk"
    assert results[0].retrieval_method == "risk_event"
