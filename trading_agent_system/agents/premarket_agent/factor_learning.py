from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .outcome_evaluator import PremarketSignalOutcomeSet


@dataclass(slots=True)
class PremarketFactorLearningState:
    version: str
    factor_weights: dict[str, float] = field(default_factory=dict)
    risk_penalties: dict[str, float] = field(default_factory=dict)
    source_adjustments: dict[str, float] = field(default_factory=dict)
    theme_adjustments: dict[str, float] = field(default_factory=dict)
    llm_reliability: dict[str, float] = field(default_factory=dict)
    sample_count: int = 0


@dataclass(slots=True)
class PremarketFactorLearningUpdate:
    previous_version: str
    next_state: PremarketFactorLearningState
    weight_deltas: dict[str, float] = field(default_factory=dict)
    risk_penalty_deltas: dict[str, float] = field(default_factory=dict)
    outcome_count: int = 0


class PremarketFactorLearningAgent:
    def __init__(self, learning_rate: float = 0.05, max_weight_step: float = 0.02) -> None:
        self.learning_rate = learning_rate
        self.max_weight_step = max_weight_step

    def update(
        self,
        current_state: PremarketFactorLearningState,
        outcome_set: PremarketSignalOutcomeSet,
    ) -> PremarketFactorLearningUpdate:
        factor_weights = dict(current_state.factor_weights)
        risk_penalties = dict(current_state.risk_penalties)
        weight_deltas: dict[str, float] = {}
        risk_penalty_deltas: dict[str, float] = {}

        for outcome in outcome_set.outcomes:
            for factor_name, factor_value in outcome.factor_scores.items():
                delta = self._clamp(self.learning_rate * outcome.outcome_score * factor_value)
                factor_weights[factor_name] = factor_weights.get(factor_name, 0.0) + delta
                weight_deltas[factor_name] = weight_deltas.get(factor_name, 0.0) + delta
            for risk_flag in outcome.risk_flags:
                delta = self._risk_delta(outcome.outcome_score)
                risk_penalties[risk_flag] = max(0.0, risk_penalties.get(risk_flag, 0.0) + delta)
                risk_penalty_deltas[risk_flag] = risk_penalty_deltas.get(risk_flag, 0.0) + delta

        next_sample_count = current_state.sample_count + len(outcome_set.outcomes)
        next_state = replace(
            current_state,
            version=f"pfl_{outcome_set.evaluation_date:%Y%m%d}_{next_sample_count:06d}",
            factor_weights=factor_weights,
            risk_penalties=risk_penalties,
            sample_count=next_sample_count,
        )
        return PremarketFactorLearningUpdate(
            previous_version=current_state.version,
            next_state=next_state,
            weight_deltas=weight_deltas,
            risk_penalty_deltas=risk_penalty_deltas,
            outcome_count=len(outcome_set.outcomes),
        )

    def _risk_delta(self, outcome_score: float) -> float:
        if outcome_score < 0:
            return self._clamp(self.learning_rate * abs(outcome_score))
        if outcome_score > 0:
            return self._clamp(-0.5 * self.learning_rate * outcome_score)
        return 0.0

    def _clamp(self, value: float) -> float:
        return max(-self.max_weight_step, min(self.max_weight_step, value))


class PremarketFactorLearningStore:
    def __init__(self, root_dir: str | Path = "data/premarket_learning") -> None:
        self.root_dir = Path(root_dir)
        self.versions_path = self.root_dir / "versions.jsonl"
        self.current_path = self.root_dir / "CURRENT"

    def list_versions(self) -> list[str]:
        return [state.version for state in self._read_versions()]

    def get_current(self) -> PremarketFactorLearningState | None:
        versions = self._read_versions()
        if not versions:
            return None
        current_version = self.current_path.read_text(encoding="utf-8").strip() if self.current_path.exists() else ""
        if current_version:
            for state in reversed(versions):
                if state.version == current_version:
                    return state
        return versions[-1]

    def save_version(self, state: PremarketFactorLearningState) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        with self.versions_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(state), sort_keys=True) + "\n")
        self.current_path.write_text(state.version, encoding="utf-8")

    def rollback_current(self, version: str) -> PremarketFactorLearningState:
        for state in reversed(self._read_versions()):
            if state.version == version:
                self.root_dir.mkdir(parents=True, exist_ok=True)
                self.current_path.write_text(version, encoding="utf-8")
                return state
        raise ValueError(f"unknown premarket factor learning version: {version}")

    def _read_versions(self) -> list[PremarketFactorLearningState]:
        if not self.versions_path.exists():
            return []
        states: list[PremarketFactorLearningState] = []
        for line in self.versions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            states.append(PremarketFactorLearningState(**json.loads(line)))
        return states
