from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .schemas import EffectiveOnePickStrategy, LearningState, OnePickSelectionConfig


class LearningStateStorePort(Protocol):
    def get_current(self, strategy_id: str | None = None) -> LearningState | dict[str, Any] | None:
        ...


class OnePickStrategyLoader:
    def __init__(
        self,
        config_path: str | Path | None = None,
        learning_store: LearningStateStorePort | None = None,
        base_config: dict[str, Any] | None = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path is not None else Path("configs/one_pick_two_day.yaml")
        self.learning_store = learning_store
        self.base_config = base_config

    def load(self) -> EffectiveOnePickStrategy:
        base = dict(self.base_config or _load_config(self.config_path))
        strategy_id = str(base.get("strategy_id", "one_pick_two_day_v1"))
        base_version = str(base.get("version", "1.0.0"))
        learning_state = self._load_learning_state(strategy_id)

        scoring_weights = dict(base.get("scoring_weights", {}))
        risk_penalties = dict(base.get("risk_penalties", {}))
        tag_adjustments = dict(base.get("tag_adjustments", {}))
        strategy_version = base_version

        if learning_state is not None:
            scoring_weights = _merge_numeric(scoring_weights, learning_state.feature_weights)
            risk_penalties = _merge_numeric(risk_penalties, learning_state.risk_penalties)
            tag_adjustments = _merge_numeric(tag_adjustments, learning_state.tag_adjustments)
            strategy_version = f"{base_version}+{learning_state.version}"

        return EffectiveOnePickStrategy(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            selection=OnePickSelectionConfig(**base.get("selection", {})),
            scoring_weights=scoring_weights,
            risk_penalties=risk_penalties,
            blocked_risk_flags=list(base.get("blocked_risk_flags", [])),
            tag_adjustments=tag_adjustments,
            entry_rule=dict(base.get("entry_rule", {})),
            exit_rule=dict(base.get("exit_rule", {})),
            learning=dict(base.get("learning", {})),
        )

    def _load_learning_state(self, strategy_id: str) -> LearningState | None:
        if self.learning_store is None:
            return None
        try:
            raw = self.learning_store.get_current(strategy_id)
        except TypeError:
            raw = self.learning_store.get_current()
        if raw is None:
            return None
        if isinstance(raw, LearningState):
            return raw
        if hasattr(raw, "version_id") and hasattr(raw, "scoring_weights"):
            return LearningState(
                strategy_id=str(getattr(raw, "strategy_id", strategy_id)),
                version=str(getattr(raw, "version_id")),
                feature_weights=dict(getattr(raw, "scoring_weights", {})),
                risk_penalties=dict(getattr(raw, "risk_penalties", {})),
                metadata=dict(getattr(raw, "metadata", {})),
            )
        if isinstance(raw, dict) and "scoring_weights" in raw:
            return LearningState(
                strategy_id=str(raw.get("strategy_id", strategy_id)),
                version=str(raw.get("version_id", raw.get("version", "unknown"))),
                feature_weights=dict(raw.get("scoring_weights", {})),
                risk_penalties=dict(raw.get("risk_penalties", {})),
                metadata=dict(raw.get("metadata", {})),
            )
        return LearningState(**raw)


def _merge_numeric(base: dict[str, float], overlay: dict[str, float]) -> dict[str, float]:
    merged = {key: float(value) for key, value in base.items()}
    for key, value in overlay.items():
        merged[key] = merged.get(key, 0.0) + float(value)
    return merged


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_config()
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = _parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {path}")
    return data


def _default_config() -> dict[str, Any]:
    return {
        "strategy_id": "one_pick_two_day_v1",
        "version": "1.0.0",
        "selection": {
            "force_pick_one": True,
            "min_confidence_to_buy": 0.60,
            "min_risk_reward_ratio": 1.80,
            "max_candidates": 20,
        },
        "scoring_weights": {
            "catalyst_strength": 0.45,
            "source_quality": 0.25,
            "evidence_support": 0.20,
            "market_confirmation": 0.10,
        },
        "risk_penalties": {"rumor": 0.30, "unverified": 0.35},
        "blocked_risk_flags": ["regulatory_inquiry", "delisting_risk"],
        "entry_rule": {"default_quantity": 100},
        "exit_rule": {"take_profit_pct": 0.04, "stop_loss_pct": 0.02},
        "learning": {"learning_rate": 0.10, "max_weight_step": 0.03},
    }


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _parse_tiny_yaml(text)
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("YAML config must contain a mapping")
    return loaded


def _parse_tiny_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, root)]
    pending_key: str | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if not isinstance(parent, list):
                if pending_key is None or not isinstance(parent, dict):
                    raise ValueError(f"unsupported YAML list line: {raw_line}")
                parent[pending_key] = []
                stack.append((indent - 1, parent[pending_key]))
                parent = parent[pending_key]
            parent.append(_coerce_scalar(line[2:].strip()))
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"unsupported YAML mapping line: {raw_line}")
        if value == "":
            parent[key] = {}
            pending_key = key
            stack.append((indent, parent[key]))
        else:
            parent[key] = _coerce_scalar(value)
            pending_key = key
    return root


def _coerce_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
