from __future__ import annotations

from datetime import datetime, timezone

from trading_agent_system.agents.one_pick_agent.candidate_generator import CandidateGenerator


def test_candidate_generator_builds_symbol_candidates_from_events_and_evidence():
    events = [
        {
            "event_id": "evt_policy",
            "symbols": ["688981.SH", "000001.SZ"],
            "title": "policy support",
            "importance": "A",
            "bias": "bullish",
            "confidence": 0.8,
            "source_rank": "official",
            "related_themes": ["semiconductor"],
            "risk_flags": [],
            "first_seen_at": datetime.now(timezone.utc),
        },
        {
            "event_id": "evt_risk",
            "symbols": ["000001.SZ"],
            "title": "unverified rumor",
            "importance": "B",
            "bias": "bullish",
            "confidence": 0.6,
            "source_rank": "social",
            "related_themes": ["bank"],
            "risk_flags": ["rumor"],
            "first_seen_at": datetime.now(timezone.utc),
        },
    ]
    evidence_packs = [
        {"evidence_id": "rag_1", "symbols": ["688981.SH"], "score": 0.9},
    ]

    candidates = CandidateGenerator().generate(events=events, evidence_packs=evidence_packs)

    by_symbol = {candidate.symbol: candidate for candidate in candidates}
    assert list(by_symbol) == ["688981.SH", "000001.SZ"]
    assert by_symbol["688981.SH"].evidence_ids == ["evt_policy", "rag_1"]
    assert by_symbol["688981.SH"].feature_scores["source_quality"] > by_symbol["000001.SZ"].feature_scores["source_quality"]
    assert "rumor" in by_symbol["000001.SZ"].risk_flags
    assert "semiconductor" in by_symbol["688981.SH"].strategy_tags
