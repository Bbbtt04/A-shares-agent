from __future__ import annotations

import json
from datetime import date, datetime, timezone

from trading_agent_system.api import app as api_module
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.storage import JsonlEventRepository


def _write_jsonl(path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n",
        encoding="utf-8",
    )


def _patch_dirs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    monkeypatch.setattr(api_module, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(api_module, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setattr(api_module, "ONE_PICK_CHECKPOINT_DIR", tmp_path / "runtime" / "checkpoints")
    monkeypatch.setattr(api_module, "ONE_PICK_LEARNING_DIR", tmp_path / "strategy_learning")


def test_one_pick_latest_returns_graceful_empty_state(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)

    response = api_module.one_pick_latest()

    assert response["status"] == "empty"
    assert response["run_id"] is None
    assert response["selected_stock"] is None
    assert response["trade_plan"] is None
    assert response["checkpoints"] == []
    assert response["learning_state"]["current_version"] is None


def test_one_pick_latest_reads_debug_snapshot_from_local_artifacts(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    trading_day = date(2026, 6, 15)
    created_at = datetime(2026, 6, 15, 1, 2, tzinfo=timezone.utc).isoformat()
    _write_jsonl(
        api_module.ONE_PICK_CHECKPOINT_DIR / "run_alpha.jsonl",
        [
            {
                "checkpoint_id": "chk_select",
                "run_id": "run_alpha",
                "trading_day": trading_day.isoformat(),
                "agent": "one_pick_agent",
                "step": "stock_selected",
                "status": "success",
                "input_refs": ["premarket:ctx"],
                "output_refs": ["selection:1"],
                "payload": {
                    "selection": {
                        "selected_symbol": "688981.SH",
                        "selected_name": "SMIC",
                        "confidence": 0.72,
                        "risk_reward_ratio": 2.1,
                        "evidence_ids": ["ev_1"],
                    }
                },
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "checkpoint_id": "chk_plan",
                "run_id": "run_alpha",
                "trading_day": trading_day.isoformat(),
                "agent": "one_pick_agent",
                "step": "trade_plan_created",
                "status": "success",
                "input_refs": ["selection:1"],
                "output_refs": ["plan:1"],
                "payload": {
                    "trade_plan": {
                        "symbol": "688981.SH",
                        "confidence": 0.72,
                        "risk_reward_ratio": 2.1,
                        "buy_reasons": ["policy catalyst"],
                        "risk_reasons": ["gap risk"],
                        "entry_price": 58.2,
                        "exit_price": 61.0,
                    }
                },
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "checkpoint_id": "chk_outcome",
                "run_id": "run_alpha",
                "trading_day": trading_day.isoformat(),
                "agent": "one_pick_agent",
                "step": "outcome_reviewed",
                "status": "success",
                "input_refs": ["fill:buy", "fill:sell"],
                "output_refs": ["outcome:1"],
                "payload": {"outcome": {"pnl_pct": 0.033, "exit_price": 60.1}},
                "created_at": created_at,
                "updated_at": created_at,
            },
        ],
    )
    repository = JsonlEventRepository(api_module.EVENT_DIR)
    repository.append_envelope(
        make_envelope(
            "one_pick.buy_filled",
            {"fill": {"symbol": "688981.SH", "side": "buy", "price": 58.2, "quantity": 100}},
            producer="one_pick_agent",
            trading_day=trading_day,
            run_id="run_alpha",
            evidence_ids=["ev_1"],
        )
    )
    TraceLogger(api_module.TRACE_DIR).record(
        agent="one_pick_agent",
        step="stock_selected",
        run_id="run_alpha",
        status="success",
        output_refs=["selection:1"],
        evidence_ids=["ev_1"],
        decision_summary="selected 688981.SH",
    )
    MetricsRecorder(api_module.METRICS_DIR).record(
        "runtime_budget_spent_llm_tokens",
        320,
        tags={"agent": "one_pick_agent"},
        run_id="run_alpha",
    )
    _write_jsonl(
        api_module.ONE_PICK_LEARNING_DIR / "one_pick_versions.jsonl",
        [
            {
                "version": "v1",
                "strategy_id": "one_pick_two_day_v1",
                "feature_weights": {"policy": 0.2},
                "created_at": created_at,
            }
        ],
    )
    (api_module.ONE_PICK_LEARNING_DIR / "one_pick_current.json").write_text(
        json.dumps({"current_version": "v1"}, ensure_ascii=False),
        encoding="utf-8",
    )

    response = api_module.one_pick_latest()

    assert response["status"] == "ok"
    assert response["run_id"] == "run_alpha"
    assert response["selected_stock"]["symbol"] == "688981.SH"
    assert response["trade_plan"]["buy_reasons"] == ["policy catalyst"]
    assert response["fills"][0]["fill"]["price"] == 58.2
    assert response["outcome"]["pnl_pct"] == 0.033
    assert response["learning_state"]["current_version"] == "v1"
    assert response["learning_update"]["feature_weights"]["policy"] == 0.2
    assert response["budget_usage"]["runtime_budget_spent_llm_tokens"] == 320
    assert response["trace_refs"][0]["trace_id"].startswith("trace_")
    assert response["evidence_refs"] == ["ev_1"]


def test_one_pick_run_filters_by_run_id_and_learning_rollback_updates_pointer(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    created_at = datetime(2026, 6, 15, 1, 2, tzinfo=timezone.utc).isoformat()
    _write_jsonl(
        api_module.ONE_PICK_CHECKPOINT_DIR / "runs.jsonl",
        [
            {
                "checkpoint_id": "chk_old",
                "run_id": "run_old",
                "agent": "one_pick_agent",
                "step": "stock_selected",
                "status": "success",
                "payload": {"selected_stock": {"symbol": "000001.SZ"}},
                "created_at": created_at,
                "updated_at": created_at,
            },
            {
                "checkpoint_id": "chk_target",
                "run_id": "run_target",
                "agent": "one_pick_agent",
                "step": "stock_selected",
                "status": "success",
                "payload": {"selected_stock": {"symbol": "600000.SH"}},
                "created_at": created_at,
                "updated_at": created_at,
            },
        ],
    )
    _write_jsonl(
        api_module.ONE_PICK_LEARNING_DIR / "one_pick_versions.jsonl",
        [
            {"version": "v1", "created_at": created_at, "feature_weights": {"policy": 0.1}},
            {"version": "v2", "created_at": created_at, "feature_weights": {"policy": 0.2}},
        ],
    )
    api_module.ONE_PICK_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    (api_module.ONE_PICK_LEARNING_DIR / "one_pick_current.json").write_text(
        json.dumps({"current_version": "v2"}),
        encoding="utf-8",
    )

    run_response = api_module.one_pick_run("run_target")
    rollback_response = api_module.one_pick_learning_rollback({"target_version": "v1"})

    assert run_response["run_id"] == "run_target"
    assert run_response["selected_stock"]["symbol"] == "600000.SH"
    assert rollback_response["learning_state"]["current_version"] == "v1"
    assert json.loads((api_module.ONE_PICK_LEARNING_DIR / "one_pick_current.json").read_text(encoding="utf-8")) == {
        "current_version": "v1"
    }
