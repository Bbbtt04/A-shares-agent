from datetime import date

from trading_agent_system.core.runtime import CheckpointStore, RuntimeCheckpoint


def test_checkpoint_store_saves_and_loads_successful_checkpoint(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")

    checkpoint = store.save_success(
        run_id="run_1",
        trading_day=date(2026, 6, 15),
        agent="one_pick",
        step="stock_selected",
        input_refs=["candidate_1"],
        output_refs=["selection_1"],
        payload={"symbol": "600519"},
    )

    loaded = store.load(run_id="run_1", step="stock_selected")

    assert isinstance(loaded, RuntimeCheckpoint)
    assert loaded == checkpoint
    assert loaded.status == "success"
    assert loaded.payload == {"symbol": "600519"}


def test_checkpoint_store_loads_latest_checkpoint_for_run(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")

    store.save_success(run_id="run_1", trading_day=None, agent="one_pick", step="first")
    latest = store.save_success(run_id="run_1", trading_day=None, agent="one_pick", step="second")

    assert store.load_latest("run_1") == latest


def test_checkpoint_store_saves_failed_checkpoint_with_error(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")

    checkpoint = store.save_failed(
        run_id="run_1",
        trading_day=None,
        agent="one_pick",
        step="trade_plan_created",
        error="structured output invalid",
        payload={"provider": "mock"},
    )

    loaded = store.load(run_id="run_1", step="trade_plan_created")
    assert loaded == checkpoint
    assert loaded.status == "failed"
    assert loaded.error == "structured output invalid"


def test_checkpoint_store_invalidates_checkpoint(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    store.save_success(run_id="run_1", trading_day=None, agent="one_pick", step="stock_selected")

    invalidated = store.invalidate(run_id="run_1", step="stock_selected", reason="force rerun")

    assert invalidated.status == "invalidated"
    assert invalidated.error == "force rerun"
    assert store.load(run_id="run_1", step="stock_selected").status == "invalidated"
    assert not store.is_completed(run_id="run_1", step="stock_selected")


def test_checkpoint_store_completed_step_supports_idempotent_resume(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")

    store.save_success(run_id="run_1", trading_day=None, agent="one_pick", step="buy_order_submitted")

    assert store.is_completed(run_id="run_1", step="buy_order_submitted")
    assert not store.is_completed(run_id="run_1", step="sell_order_submitted")


def test_checkpoint_store_rebuilds_index_from_jsonl(tmp_path):
    base_dir = tmp_path / "checkpoints"
    first = CheckpointStore(base_dir)
    first.save_success(run_id="run_1", trading_day=None, agent="one_pick", step="stock_selected")

    second = CheckpointStore(base_dir)

    assert second.is_completed(run_id="run_1", step="stock_selected")
