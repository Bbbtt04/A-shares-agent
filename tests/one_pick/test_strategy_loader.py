from __future__ import annotations

from pathlib import Path

from trading_agent_system.agents.one_pick_agent.schemas import LearningState
from trading_agent_system.agents.one_pick_agent.strategy_loader import OnePickStrategyLoader
from trading_agent_system.core.strategy_learning import LearningStateStore


class FakeLearningStore:
    def get_current(self, strategy_id: str) -> LearningState:
        assert strategy_id == "one_pick_two_day_v1"
        return LearningState(
            strategy_id=strategy_id,
            version="learned-2",
            feature_weights={"catalyst_strength": 0.2},
            risk_penalties={"rumor": 0.4},
            tag_adjustments={"semiconductor": 0.1},
        )


def test_strategy_loader_merges_base_config_with_learning_state(tmp_path: Path):
    config_path = tmp_path / "one_pick.yaml"
    config_path.write_text(
        """
strategy_id: one_pick_two_day_v1
version: 1.0.0
selection:
  force_pick_one: true
  min_confidence_to_buy: 0.6
  min_risk_reward_ratio: 1.8
  max_candidates: 20
scoring_weights:
  catalyst_strength: 0.5
  source_quality: 0.3
risk_penalties:
  regulatory_inquiry: 0.8
blocked_risk_flags:
  - delisting_risk
entry_rule:
  default_quantity: 100
exit_rule:
  take_profit_pct: 0.04
  stop_loss_pct: 0.02
learning:
  learning_rate: 0.1
  max_weight_step: 0.05
""",
        encoding="utf-8",
    )

    strategy = OnePickStrategyLoader(config_path=config_path, learning_store=FakeLearningStore()).load()

    assert strategy.strategy_id == "one_pick_two_day_v1"
    assert strategy.strategy_version == "1.0.0+learned-2"
    assert strategy.selection.force_pick_one is True
    assert strategy.scoring_weights["catalyst_strength"] == 0.7
    assert strategy.risk_penalties["rumor"] == 0.4
    assert strategy.risk_penalties["regulatory_inquiry"] == 0.8
    assert strategy.tag_adjustments["semiconductor"] == 0.1


def test_strategy_loader_merges_m15_learning_store(tmp_path: Path):
    config_path = tmp_path / "one_pick.yaml"
    config_path.write_text(
        """
strategy_id: one_pick_two_day_v1
version: 1.0.0
selection:
  force_pick_one: true
scoring_weights:
  catalyst_strength: 0.5
risk_penalties:
  rumor: 0.2
entry_rule:
  default_quantity: 100
exit_rule:
  take_profit_pct: 0.04
  stop_loss_pct: 0.02
""",
        encoding="utf-8",
    )
    store = LearningStateStore(tmp_path / "learning")
    store.create_next_version(
        scoring_weights={"catalyst_strength": 0.1},
        risk_penalties={"rumor": 0.3},
        metadata={"source": "review"},
    )

    strategy = OnePickStrategyLoader(config_path=config_path, learning_store=store).load()

    assert strategy.strategy_version == "1.0.0+one_pick_two_day_v1-v000001"
    assert strategy.scoring_weights["catalyst_strength"] == 0.6
    assert strategy.risk_penalties["rumor"] == 0.5
