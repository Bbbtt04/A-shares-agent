from __future__ import annotations

import sqlite3

from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


EXPECTED_TABLES = {
    "strategy_runs",
    "premarket_events",
    "semantic_reviews",
    "factor_scores",
    "strategy_recommendations",
    "strategy_prices",
    "strategy_outcomes",
    "factor_weight_versions",
    "decision_audit_logs",
}


def test_store_initializes_sqlite_database_with_required_tables(tmp_path):
    db_path = tmp_path / "strategy-ledger.sqlite"

    StrategyLedgerStore(db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

    assert EXPECTED_TABLES.issubset({row[0] for row in rows})


def test_runs_start_and_finish_with_json_metadata(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")

    started = store.runs.start(
        run_id="run-001",
        trading_day="2026-06-19",
        run_type="premarket_recommend",
        metadata={"deadline": "09:15", "fallback": False},
    )
    finished = store.runs.finish("run-001", status="degraded", error_message="llm timeout")

    assert started["status"] == "running"
    assert started["metadata"] == {"deadline": "09:15", "fallback": False}
    assert finished["status"] == "degraded"
    assert finished["error_message"] == "llm timeout"
    assert finished["metadata"] == {"deadline": "09:15", "fallback": False}
    assert finished["finished_at"] is not None


def test_recommendations_round_trip_json_fields_and_upsert_by_id(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    recommendation = {
        "recommendation_id": "rec-001",
        "run_id": "run-001",
        "trading_day": "2026-06-19",
        "symbol": "600519",
        "action": "buy",
        "priority": 1,
        "confidence": 0.82,
        "signal_score": 0.76,
        "expected_risk_reward": 1.8,
        "entry_conditions": [{"type": "open_above", "price": 100.0}],
        "avoid_conditions": ["limit_up_open"],
        "risk_notes": ["crowded theme"],
        "handoff_payload": {"lot_size": 100, "strategy": "premarket"},
    }

    saved = store.recommendations.save(recommendation)
    updated = dict(recommendation, confidence=0.9, risk_notes=["updated"])
    store.recommendations.save(updated)

    assert saved["entry_conditions"] == recommendation["entry_conditions"]
    assert store.recommendations.latest() == dict(updated, created_at=store.recommendations.latest()["created_at"])
    assert store.recommendations.latest("2026-06-19")["risk_notes"] == ["updated"]
    assert store.recommendations.by_day("2026-06-19")[0]["confidence"] == 0.9
    assert store.recommendations.by_day("2026-06-18") == []

    count = store.connection.execute("SELECT COUNT(*) FROM strategy_recommendations").fetchone()[0]
    assert count == 1


def test_prices_round_trip_raw_payload_and_upsert_by_unique_price_key(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    price = {
        "trading_day": "2026-06-19",
        "symbol": "600519",
        "price_type": "buy_open",
        "price_time": "09:30",
        "price": 100.5,
        "source": "test-feed",
        "raw_payload": {"open": "100.50", "status": "ok"},
    }

    store.prices.save(price)
    store.prices.save(dict(price, price=101.25, raw_payload={"open": "101.25"}))

    loaded = store.prices.get("2026-06-19", "600519", "buy_open")

    assert loaded["price"] == 101.25
    assert loaded["raw_payload"] == {"open": "101.25"}
    assert store.prices.get("2026-06-19", "600519", "sell_open") is None
    count = store.connection.execute("SELECT COUNT(*) FROM strategy_prices").fetchone()[0]
    assert count == 1


def test_outcomes_round_trip_attribution_and_upsert_by_id(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    outcome = {
        "outcome_id": "out-001",
        "recommendation_id": "rec-001",
        "buy_trading_day": "2026-06-18",
        "sell_trading_day": "2026-06-19",
        "symbol": "600519",
        "buy_price": 100.0,
        "sell_price": 104.0,
        "return_pct": 0.04,
        "hit_result": "win",
        "outcome_label": "strong_open",
        "attribution": {"news_strength": 0.03},
    }

    store.outcomes.save(outcome)
    store.outcomes.save(dict(outcome, return_pct=0.05, attribution={"news_strength": 0.04}))

    loaded = store.outcomes.by_recommendation("rec-001")

    assert loaded == [dict(outcome, return_pct=0.05, attribution={"news_strength": 0.04}, created_at=loaded[0]["created_at"])]
    assert store.outcomes.by_recommendation("missing") == []
    assert store.outcomes.latest()["outcome_id"] == "out-001"
    count = store.connection.execute("SELECT COUNT(*) FROM strategy_outcomes").fetchone()[0]
    assert count == 1


def test_factor_weights_active_activate_and_rollback(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    first = {
        "version": "weights-v1",
        "created_by_run_id": "run-001",
        "previous_version": None,
        "is_active": True,
        "weights": {"news_strength": 0.4},
        "learning_summary": {"seed": True},
    }
    second = {
        "version": "weights-v2",
        "created_by_run_id": "run-002",
        "previous_version": "weights-v1",
        "is_active": True,
        "weights": {"news_strength": 0.43},
        "learning_summary": {"sample": "out-001"},
    }

    store.weights.save_version(first)
    store.weights.save_version(second)

    assert store.weights.active()["version"] == "weights-v2"
    assert store.weights.active()["weights"] == {"news_strength": 0.43}

    rolled_back = store.weights.activate("weights-v1")

    assert rolled_back["version"] == "weights-v1"
    assert store.weights.active()["version"] == "weights-v1"


def test_audit_logs_round_trip_json_fields_and_query_by_run(tmp_path):
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    first = {
        "audit_id": "audit-001",
        "run_id": "run-001",
        "trading_day": "2026-06-19",
        "symbol": "600519",
        "stage": "factor_scoring",
        "input": {"events": ["evt-1"]},
        "output": {"score": 0.76},
        "reasoning_summary": "strong catalyst but crowded",
        "model_name": None,
        "latency_ms": 12.5,
    }
    second = dict(first, audit_id="audit-002", stage="recommendation")

    store.audits.log(first)
    store.audits.log(second)
    store.audits.log(dict(first, output={"score": 0.8}))

    loaded = store.audits.by_run("run-001")

    assert [row["audit_id"] for row in loaded] == ["audit-001", "audit-002"]
    assert loaded[0]["input"] == {"events": ["evt-1"]}
    assert loaded[0]["output"] == {"score": 0.8}
    assert store.audits.by_run("missing") == []
    count = store.connection.execute("SELECT COUNT(*) FROM decision_audit_logs").fetchone()[0]
    assert count == 2
