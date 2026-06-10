from datetime import date

from trading_agent_system.agents.premarket_agent.rag.evidence_pack_builder import EvidencePackBuilder
from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalResult


def _result(result_id, cluster_id, score, confidence=0.9):
    return RetrievalResult(
        result_id=result_id,
        task_id="task_1",
        doc_id=result_id,
        event_cluster_id=cluster_id,
        content="公司公告收到监管函",
        title="监管函",
        source="上交所",
        source_type="exchange_notice",
        source_rank=1.0,
        symbols=["600000.SH"],
        retrieval_method="structured",
        raw_score=score,
        final_score=score,
        evidence_ids=[result_id],
        confidence=confidence,
    )


def test_evidence_pack_dedups_event_clusters_and_cites_items():
    builder = EvidencePackBuilder(max_tokens=1200, max_per_event_cluster=1)

    pack = builder.build(
        trading_day=date(2026, 6, 10),
        premarket_window_id="pmw_20260610",
        section="portfolio_risks",
        query="持仓风险",
        results=[_result("ev_1", "cluster_1", 0.9), _result("ev_2", "cluster_1", 0.8)],
    )

    assert len(pack.items) == 1
    assert pack.dropped_duplicates == 1
    assert pack.items[0].citation_label == "[ev_1]"
