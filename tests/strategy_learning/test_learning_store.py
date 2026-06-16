from __future__ import annotations

import json

from trading_agent_system.core.strategy_learning.store import LearningStateStore


def test_empty_store_has_no_versions_or_current(tmp_path):
    store = LearningStateStore(tmp_path)

    assert store.list_versions() == []
    assert store.get_current() is None


def test_create_first_version_appends_record_and_sets_current(tmp_path):
    store = LearningStateStore(tmp_path)

    created = store.create_next_version(
        scoring_weights={"news_strength": 0.4},
        risk_penalties={"rumor": 0.2},
        confidence_penalties={},
        metadata={"source": "seed"},
    )

    assert created.version == 1
    assert created.previous_version_id is None
    assert created.scoring_weights == {"news_strength": 0.4}
    assert store.get_current() == created
    assert store.current_pointer_path.exists()

    records = store.versions_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["version_id"] == created.version_id


def test_create_next_version_links_to_previous_and_never_overwrites(tmp_path):
    store = LearningStateStore(tmp_path)
    first = store.create_next_version(scoring_weights={"news_strength": 0.4})

    second = store.create_next_version(scoring_weights={"news_strength": 0.45})

    assert second.version == 2
    assert second.previous_version_id == first.version_id
    assert store.get_current() == second
    assert [version.version_id for version in store.list_versions()] == [
        first.version_id,
        second.version_id,
    ]
    assert len(store.versions_path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_rollback_moves_current_pointer_without_rewriting_versions(tmp_path):
    store = LearningStateStore(tmp_path)
    first = store.create_next_version(scoring_weights={"news_strength": 0.4})
    second = store.create_next_version(scoring_weights={"news_strength": 0.45})

    audit_payload = store.rollback_current(
        target_version_id=first.version_id,
        reason="bad live outcome",
        actor="risk-review",
    )

    assert store.get_current() == first
    assert len(store.versions_path.read_text(encoding="utf-8").strip().splitlines()) == 2
    assert audit_payload == {
        "event_type": "strategy_learning.rollback",
        "strategy_id": "one_pick_two_day_v1",
        "from_version_id": second.version_id,
        "to_version_id": first.version_id,
        "reason": "bad live outcome",
        "actor": "risk-review",
        "payload": {
            "from_version": 2,
            "to_version": 1,
            "from_created_at": second.created_at.isoformat(),
            "to_created_at": first.created_at.isoformat(),
        },
    }
