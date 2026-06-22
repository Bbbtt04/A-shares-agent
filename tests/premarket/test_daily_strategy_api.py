from __future__ import annotations

from datetime import date

from trading_agent_system.api import app as api_module
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


def test_daily_strategy_latest_reads_database_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "DAILY_STRATEGY_DB", tmp_path / "daily_strategy.sqlite")
    store = StrategyLedgerStore(api_module.DAILY_STRATEGY_DB)
    store.runs.start("run_today", date(2026, 6, 19), "premarket_recommend", metadata={"deadline": "09:15"})
    store.recommendations.save(
        {
            "recommendation_id": "rec_today",
            "run_id": "run_today",
            "trading_day": "2026-06-19",
            "symbol": "600519.SH",
            "action": "buy",
            "priority": 1,
            "confidence": 0.82,
            "signal_score": 0.71,
            "expected_risk_reward": 1.9,
            "entry_conditions": ["open confirms theme"],
            "avoid_conditions": ["fresh negative filing"],
            "risk_notes": ["crowding medium"],
            "handoff_payload": {"version": "premarket_strategy_handoff.v1"},
        }
    )
    store.outcomes.save(
        {
            "outcome_id": "outcome_yesterday",
            "recommendation_id": "rec_yesterday",
            "buy_trading_day": "2026-06-18",
            "sell_trading_day": "2026-06-19",
            "symbol": "300229.SZ",
            "buy_price": 10.0,
            "sell_price": 10.5,
            "return_pct": 0.05,
            "hit_result": "win",
            "outcome_label": "overnight_open_win",
            "attribution": {"catalyst_strength": 0.12},
        }
    )
    store.weights.save_version(
        {
            "version": "w_20260619_001",
            "created_by_run_id": "settle_run",
            "previous_version": None,
            "is_active": True,
            "weights": {"catalyst_strength": 0.16},
            "learning_summary": {"sample_count": 1},
        }
    )

    response = api_module.daily_strategy_latest()

    assert response["status"] == "ok"
    assert response["recommendation"]["symbol"] == "600519.SH"
    assert response["recommendation"]["action"] == "buy"
    assert response["latest_outcome"]["return_pct"] == 0.05
    assert response["active_weight_version"]["version"] == "w_20260619_001"


def test_daily_strategy_audit_returns_run_timeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "DAILY_STRATEGY_DB", tmp_path / "daily_strategy.sqlite")
    store = StrategyLedgerStore(api_module.DAILY_STRATEGY_DB)
    store.audits.log(
        {
            "audit_id": "audit_1",
            "run_id": "run_today",
            "trading_day": "2026-06-19",
            "symbol": "600519.SH",
            "stage": "factor_scoring",
            "input": {"reviews": 1},
            "output": {"scores": 1},
            "reasoning_summary": "semantic review adjusted factors",
            "model_name": None,
            "latency_ms": 12.5,
        }
    )

    response = api_module.daily_strategy_audit("run_today")

    assert response["run_id"] == "run_today"
    assert response["timeline"][0]["stage"] == "factor_scoring"
    assert response["timeline"][0]["output"]["scores"] == 1


def test_run_all_includes_daily_strategy_jobs(monkeypatch) -> None:
    called: list[str] = []

    def fake_run_job(job: str, report_date: date) -> api_module.RunResult:
        called.append(job)
        return api_module.RunResult(
            job=job,
            label=job,
            command=["python", job],
            status="success",
            returncode=0,
            elapsed_ms=1,
            stdout="{}",
            stderr="",
            parsed={},
        )

    monkeypatch.setattr(api_module, "_run_job", fake_run_job)

    response = api_module.run_all(api_module.RunRequest(date=date(2026, 6, 19)))

    assert response.status == "success"
    assert called[:3] == ["premarket", "daily_strategy_recommendation", "daily_strategy_settlement"]
