from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class PremarketSignalOutcome:
    symbol: str
    signal_date: date
    evaluation_date: date
    next_day_open_return: float
    next_day_high_return: float
    next_day_close_return: float
    max_favorable_excursion: float
    max_adverse_excursion: float
    relative_return_vs_index: float
    outcome_score: float
    factor_scores: dict[str, float] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    manual_review_score: float | None = None


@dataclass(slots=True)
class PremarketSignalOutcomeSet:
    outcome_id: str
    signal_date: date
    evaluation_date: date
    outcomes: list[PremarketSignalOutcome] = field(default_factory=list)


class PremarketSignalOutcomeEvaluator:
    def evaluate(
        self,
        score_set: Any,
        market_results: dict[str, dict[str, float]],
        index_return: float = 0.0,
        evaluation_date: date | None = None,
    ) -> PremarketSignalOutcomeSet:
        signal_date = self._signal_date(score_set)
        evaluated_at = evaluation_date or date.today()
        outcomes: list[PremarketSignalOutcome] = []
        for signal in self._signals(score_set):
            symbol = str(getattr(signal, "symbol"))
            if symbol not in market_results:
                continue
            market = market_results[symbol]
            open_return = self._return_for(market, "open")
            high_return = self._return_for(market, "high")
            close_return = self._return_for(market, "close")
            low_return = self._return_for(market, "low", default=min(open_return, high_return, close_return))
            max_favorable = max(0.0, open_return, high_return, close_return)
            max_adverse = min(0.0, open_return, high_return, close_return, low_return)
            relative = close_return - index_return
            formula_score = (
                0.35 * close_return
                + 0.35 * max_favorable
                - 0.25 * abs(max_adverse)
                + 0.20 * relative
            )
            manual_score = self._manual_review_score(signal)
            outcome_score = formula_score
            if manual_score is not None:
                outcome_score = 0.8 * formula_score + 0.2 * self._normalize_manual_score(manual_score)
            outcomes.append(
                PremarketSignalOutcome(
                    symbol=symbol,
                    signal_date=signal_date,
                    evaluation_date=evaluated_at,
                    next_day_open_return=open_return,
                    next_day_high_return=high_return,
                    next_day_close_return=close_return,
                    max_favorable_excursion=max_favorable,
                    max_adverse_excursion=max_adverse,
                    relative_return_vs_index=relative,
                    manual_review_score=manual_score,
                    outcome_score=outcome_score,
                    factor_scores=self._factor_scores(signal),
                    risk_flags=list(getattr(signal, "risk_flags", []) or []),
                )
            )
        return PremarketSignalOutcomeSet(
            outcome_id=f"pso_{signal_date:%Y%m%d}_{evaluated_at:%Y%m%d}",
            signal_date=signal_date,
            evaluation_date=evaluated_at,
            outcomes=outcomes,
        )

    def _signals(self, score_set: Any) -> list[Any]:
        signals: list[Any] = []
        for bucket in ("conservative", "opportunity", "watch", "recommendations", "scores", "outcomes"):
            values = getattr(score_set, bucket, None)
            if values:
                signals.extend(values)
        return signals

    def _signal_date(self, score_set: Any) -> date:
        value = getattr(score_set, "signal_date", None) or getattr(score_set, "trading_day", None) or getattr(score_set, "date", None)
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        return date.today()

    def _return_for(self, market: dict[str, float], field_name: str, default: float | None = None) -> float:
        return_key = f"{field_name}_return"
        if return_key in market:
            return float(market[return_key])
        if field_name in market and "reference" in market:
            reference = float(market["reference"])
            if reference == 0:
                raise ValueError("reference price must be non-zero")
            return float(market[field_name]) / reference - 1.0
        if default is not None:
            return default
        raise ValueError(f"market result missing {return_key} or {field_name}/reference")

    def _factor_scores(self, signal: Any) -> dict[str, float]:
        if hasattr(signal, "factor_scores"):
            return self._numeric_dict(getattr(signal, "factor_scores"))
        decision_trace = getattr(signal, "decision_trace", {}) or {}
        return self._numeric_dict(decision_trace.get("score_breakdown", {}))

    def _numeric_dict(self, values: Any) -> dict[str, float]:
        if not isinstance(values, dict):
            return {}
        return {str(key): float(value) for key, value in values.items() if isinstance(value, int | float)}

    def _manual_review_score(self, signal: Any) -> float | None:
        value = getattr(signal, "manual_review_score", None)
        if value is None:
            value = (getattr(signal, "decision_trace", {}) or {}).get("manual_review_score")
        return None if value is None else float(value)

    def _normalize_manual_score(self, value: float) -> float:
        if -1.0 <= value <= 1.0:
            return value
        return max(-1.0, min(1.0, (value - 50.0) / 50.0))
