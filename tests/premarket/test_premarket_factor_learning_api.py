from __future__ import annotations

import json
from datetime import date

from trading_agent_system.api import app as api_module
from trading_agent_system.agents.premarket_agent.factor_learning import (
    PremarketFactorLearningState,
    PremarketFactorLearningStore,
)
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.storage import JsonlEventRepository


def test_premarket_recommendations_latest_reads_factor_pipeline_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    repository = JsonlEventRepository(api_module.EVENT_DIR)
    trading_day = date(2026, 6, 19)
    repository.append_envelope(
        make_envelope(
            "premarket.strategy_recommendations",
            {
                "recommendation_id": "rec_1",
                "trading_day": trading_day.isoformat(),
                "recommendations": [{"symbol": "300229.SZ", "action": "watch", "signal_score": 0.58}],
            },
            producer="premarket_factor_pipeline",
            trading_day=trading_day,
            run_id="pfl_run",
            evidence_ids=["ev_1"],
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.factor_scores",
            {"score_id": "score_1", "scores": [{"symbol": "300229.SZ", "signal_score": 0.58}]},
            producer="premarket_factor_pipeline",
            trading_day=trading_day,
            run_id="pfl_run",
        )
    )

    response = api_module.premarket_recommendations_latest()

    assert response["status"] == "ok"
    assert response["recommendations"]["payload"]["recommendations"][0]["symbol"] == "300229.SZ"
    assert response["factor_scores"]["payload"]["score_id"] == "score_1"
    assert response["recommendations"]["event"]["run_id"] == "pfl_run"


def test_premarket_factor_learning_state_and_rollback_use_versioned_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "PREMARKET_LEARNING_DIR", tmp_path / "premarket_learning")
    store = PremarketFactorLearningStore(api_module.PREMARKET_LEARNING_DIR)
    store.save_version(PremarketFactorLearningState(version="pfl_20260618_000001", factor_weights={"company_fit": 0.1}, sample_count=1))
    store.save_version(PremarketFactorLearningState(version="pfl_20260619_000002", factor_weights={"company_fit": 0.2}, sample_count=2))

    state_response = api_module.premarket_factor_learning_state()
    rollback_response = api_module.premarket_factor_learning_rollback({"target_version": "pfl_20260618_000001"})

    assert state_response["learning_state"]["version"] == "pfl_20260619_000002"
    assert state_response["versions"] == ["pfl_20260618_000001", "pfl_20260619_000002"]
    assert rollback_response["learning_state"]["version"] == "pfl_20260618_000001"
    assert json.loads((api_module.PREMARKET_LEARNING_DIR / "versions.jsonl").read_text(encoding="utf-8").splitlines()[0])["version"] == "pfl_20260618_000001"


def test_premarket_factor_learning_evaluate_updates_learning_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "PREMARKET_LEARNING_DIR", tmp_path / "premarket_learning")

    response = api_module.premarket_factor_learning_evaluate(
        {
            "score_set": {
                "score_id": "score_1",
                "trading_day": "2026-06-18",
                "generated_at": "2026-06-18T08:30:00+00:00",
                "scores": [
                    {
                        "symbol": "300229.SZ",
                        "theme": "AI",
                        "signal_score": 0.7,
                        "confidence": 0.8,
                        "recommendation": "candidate",
                        "factor_scores": {"company_fit": 0.9},
                        "factor_contributions": {"company_fit": 0.135},
                        "risk_flags": ["crowding_high"],
                        "evidence_ids": ["ev_1"],
                        "reasons": ["semantic review supports company fit"],
                    }
                ],
            },
            "market_results": {
                "300229.SZ": {"open_return": 0.01, "high_return": 0.05, "close_return": 0.03, "low_return": -0.01}
            },
            "index_return": 0.0,
            "evaluation_date": "2026-06-19",
        }
    )

    assert response["outcome_set"]["outcomes"][0]["symbol"] == "300229.SZ"
    assert response["learning_update"]["next_state"]["version"] == "pfl_20260619_000001"
    assert response["learning_state"]["sample_count"] == 1
    assert PremarketFactorLearningStore(api_module.PREMARKET_LEARNING_DIR).get_current().version == "pfl_20260619_000001"
