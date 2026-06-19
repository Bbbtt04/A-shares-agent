from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any

from .outcome_evaluator import PremarketSignalOutcome, PremarketSignalOutcomeSet


@dataclass(slots=True)
class DailyStrategyPrice:
    trading_day: date
    symbol: str
    price_type: str
    price_time: str
    price: float
    source: str = "provider"
    raw_payload: dict[str, Any] | None = None


@dataclass(slots=True)
class DailyStrategyOutcome:
    outcome_id: str
    recommendation_id: str
    buy_trading_day: date
    sell_trading_day: date
    symbol: str
    buy_price: float | None
    sell_price: float | None
    return_pct: float | None
    hit_result: str
    outcome_label: str
    attribution: dict[str, Any]


@dataclass(slots=True)
class DailySettlementResult:
    status: str
    today: date
    yesterday: date
    recommendation: Any | None = None
    outcome: DailyStrategyOutcome | None = None
    learning_update: Any | None = None


class DailyStrategySettlementService:
    def __init__(
        self,
        *,
        calendar: Any,
        recommendation_repository: Any,
        price_provider: Any,
        price_repository: Any,
        outcome_repository: Any,
        learning_agent: Any,
        factor_weight_repository: Any,
        audit_repository: Any,
    ) -> None:
        self.calendar = calendar
        self.recommendation_repository = recommendation_repository
        self.price_provider = price_provider
        self.price_repository = price_repository
        self.outcome_repository = outcome_repository
        self.learning_agent = learning_agent
        self.factor_weight_repository = factor_weight_repository
        self.audit_repository = audit_repository

    def settle(self, today: date) -> DailySettlementResult:
        yesterday = self.calendar.previous_trading_day(today)
        recommendation = self._find_official_recommendation(yesterday)
        if recommendation is None:
            result = DailySettlementResult(status="skipped", today=today, yesterday=yesterday)
            self._log(
                stage="settlement",
                trading_day=today,
                symbol=None,
                input={"yesterday": yesterday.isoformat()},
                output={"status": "skipped", "reason": "no_official_recommendation"},
                reasoning_summary="No official recommendation found for the previous trading day.",
            )
            return result

        symbol = str(self._field(recommendation, "symbol"))
        buy_price = self._get_or_fetch_open_price(yesterday, symbol, "buy_open")
        sell_price = self._get_or_fetch_open_price(today, symbol, "sell_open")
        outcome = self._build_outcome(
            recommendation=recommendation,
            buy_trading_day=yesterday,
            sell_trading_day=today,
            buy_price=buy_price,
            sell_price=sell_price,
        )
        self._save(self.outcome_repository, outcome)
        self._log(
            stage="settlement",
            trading_day=today,
            symbol=symbol,
            input={"recommendation": self._plain(recommendation)},
            output={"outcome": self._plain(outcome), "status": self._status_for(outcome.hit_result)},
            reasoning_summary="Settled the previous official recommendation against 09:30 open prices.",
        )

        status = self._status_for(outcome.hit_result)
        learning_update = None
        if self._is_learning_eligible(recommendation, outcome):
            learning_update = self._run_learning(recommendation, outcome)
            self._save_learning_update(learning_update)
            self._log(
                stage="learning",
                trading_day=today,
                symbol=symbol,
                input={"outcome": self._plain(outcome)},
                output={"status": "success", "learning_update": self._plain(learning_update)},
                reasoning_summary="Updated premarket factor learning from an eligible buy outcome.",
            )
        elif outcome.hit_result in {"win", "loss", "flat"}:
            self._log(
                stage="learning",
                trading_day=today,
                symbol=symbol,
                input={"outcome": self._plain(outcome)},
                output={"status": "skipped", "reason": "recommendation_action_not_buy"},
                reasoning_summary="Learning was skipped because the recommendation was not a buy action.",
            )

        return DailySettlementResult(
            status=status,
            today=today,
            yesterday=yesterday,
            recommendation=recommendation,
            outcome=outcome,
            learning_update=learning_update,
        )

    def _find_official_recommendation(self, trading_day: date) -> Any | None:
        method_names = (
            "find_official",
            "get_official",
            "get_official_for_day",
            "load_official",
            "load_official_buy",
            "find_official_buy",
        )
        for method_name in method_names:
            method = getattr(self.recommendation_repository, method_name, None)
            if method is not None:
                return method(trading_day)
        raise AttributeError("recommendation_repository must provide an official recommendation lookup method")

    def _get_or_fetch_open_price(self, trading_day: date, symbol: str, price_type: str) -> float | None:
        cached = self._get_cached_price(trading_day, symbol, price_type)
        if cached is not None:
            return cached

        fetched = self.price_provider.get_open_price(trading_day, symbol)
        if fetched is None:
            return None

        price = float(fetched)
        self._save(
            self.price_repository,
            DailyStrategyPrice(
                trading_day=trading_day,
                symbol=symbol,
                price_type=price_type,
                price_time="09:30",
                price=price,
                raw_payload={},
            ),
        )
        return price

    def _get_cached_price(self, trading_day: date, symbol: str, price_type: str) -> float | None:
        get_price = getattr(self.price_repository, "get")
        try:
            value = get_price(trading_day, symbol, price_type)
        except TypeError:
            value = get_price(trading_day=trading_day, symbol=symbol, price_type=price_type, price_time="09:30")
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get("price")
        if hasattr(value, "price"):
            value = getattr(value, "price")
        return None if value is None else float(value)

    def _build_outcome(
        self,
        *,
        recommendation: Any,
        buy_trading_day: date,
        sell_trading_day: date,
        buy_price: float | None,
        sell_price: float | None,
    ) -> DailyStrategyOutcome:
        hit_result = self._hit_result(buy_price, sell_price)
        return_pct = None
        if hit_result in {"win", "loss", "flat"}:
            return_pct = (float(sell_price) - float(buy_price)) / float(buy_price)

        recommendation_id = str(self._field(recommendation, "recommendation_id", "unknown"))
        symbol = str(self._field(recommendation, "symbol"))
        return DailyStrategyOutcome(
            outcome_id=f"dso_{recommendation_id}_{sell_trading_day:%Y%m%d}",
            recommendation_id=recommendation_id,
            buy_trading_day=buy_trading_day,
            sell_trading_day=sell_trading_day,
            symbol=symbol,
            buy_price=buy_price,
            sell_price=sell_price,
            return_pct=return_pct,
            hit_result=hit_result,
            outcome_label=hit_result,
            attribution={
                "action": self._field(recommendation, "action", None),
                "factor_scores": self._factor_scores(recommendation),
                "risk_flags": self._risk_flags(recommendation),
            },
        )

    def _hit_result(self, buy_price: float | None, sell_price: float | None) -> str:
        if buy_price is None or sell_price is None:
            return "pending_price"
        if buy_price <= 0 or sell_price <= 0:
            return "invalid_price"
        return_pct = (sell_price - buy_price) / buy_price
        if return_pct > 0.002:
            return "win"
        if return_pct < -0.002:
            return "loss"
        return "flat"

    def _status_for(self, hit_result: str) -> str:
        if hit_result == "pending_price":
            return "pending_price"
        if hit_result == "invalid_price":
            return "invalid_price"
        return "success"

    def _is_learning_eligible(self, recommendation: Any, outcome: DailyStrategyOutcome) -> bool:
        return self._field(recommendation, "action", None) == "buy" and outcome.hit_result in {"win", "loss", "flat"}

    def _run_learning(self, recommendation: Any, outcome: DailyStrategyOutcome) -> Any:
        current_state = self._load_active_learning_state()
        outcome_set = PremarketSignalOutcomeSet(
            outcome_id=f"pso_{outcome.buy_trading_day:%Y%m%d}_{outcome.sell_trading_day:%Y%m%d}",
            signal_date=outcome.buy_trading_day,
            evaluation_date=outcome.sell_trading_day,
            outcomes=[
                PremarketSignalOutcome(
                    symbol=outcome.symbol,
                    signal_date=outcome.buy_trading_day,
                    evaluation_date=outcome.sell_trading_day,
                    next_day_open_return=float(outcome.return_pct or 0.0),
                    next_day_high_return=float(outcome.return_pct or 0.0),
                    next_day_close_return=float(outcome.return_pct or 0.0),
                    max_favorable_excursion=max(0.0, float(outcome.return_pct or 0.0)),
                    max_adverse_excursion=min(0.0, float(outcome.return_pct or 0.0)),
                    relative_return_vs_index=float(outcome.return_pct or 0.0),
                    outcome_score=float(outcome.return_pct or 0.0),
                    factor_scores=self._factor_scores(recommendation),
                    risk_flags=self._risk_flags(recommendation),
                )
            ],
        )
        update = getattr(self.learning_agent, "update", None)
        if update is not None:
            return update(current_state, outcome_set)
        learn = getattr(self.learning_agent, "learn", None)
        if learn is not None:
            return learn(current_state, outcome_set)
        raise AttributeError("learning_agent must provide update or learn")

    def _load_active_learning_state(self) -> Any:
        for method_name in ("load_active", "get_active", "get_current"):
            method = getattr(self.factor_weight_repository, method_name, None)
            if method is not None:
                return method()
        raise AttributeError("factor_weight_repository must provide an active state loader")

    def _save_learning_update(self, learning_update: Any) -> None:
        for method_name in ("save_new_active_version", "save_update", "save"):
            method = getattr(self.factor_weight_repository, method_name, None)
            if method is not None:
                method(learning_update)
                return
        save_version = getattr(self.factor_weight_repository, "save_version", None)
        if save_version is not None and hasattr(learning_update, "next_state"):
            save_version(learning_update.next_state)
            return
        raise AttributeError("factor_weight_repository must provide a learning update save method")

    def _save(self, repository: Any, item: Any) -> None:
        save = getattr(repository, "save")
        try:
            save(item)
        except (TypeError, AttributeError):
            save(self._plain(item))

    def _log(
        self,
        *,
        stage: str,
        trading_day: date,
        symbol: str | None,
        input: dict[str, Any],
        output: dict[str, Any],
        reasoning_summary: str,
    ) -> None:
        log = getattr(self.audit_repository, "log")
        payload = {
            "audit_id": f"settlement_{trading_day.isoformat()}_{stage}_{symbol or 'all'}",
            "run_id": f"settlement_{trading_day.isoformat()}",
            "stage": stage,
            "trading_day": trading_day,
            "symbol": symbol,
            "input": input,
            "output": output,
            "reasoning_summary": reasoning_summary,
        }
        try:
            log(payload)
        except TypeError:
            log(**payload)

    def _factor_scores(self, recommendation: Any) -> dict[str, float]:
        values = self._field(recommendation, "factor_scores", None)
        if values is None:
            handoff_payload = self._field(recommendation, "handoff_payload", {}) or {}
            values = handoff_payload.get("factor_scores") if isinstance(handoff_payload, dict) else None
        if values is None:
            values = (self._field(recommendation, "decision_trace", {}) or {}).get("score_breakdown", {})
        if not isinstance(values, dict):
            return {}
        return {str(key): float(value) for key, value in values.items() if isinstance(value, int | float)}

    def _risk_flags(self, recommendation: Any) -> list[str]:
        flags = self._field(recommendation, "risk_flags", None)
        if flags is None:
            flags = self._field(recommendation, "risk_notes", None)
        return [str(flag) for flag in (flags or [])]

    def _field(self, source: Any, name: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(name, default)
        return getattr(source, name, default)

    def _plain(self, value: Any) -> Any:
        if is_dataclass(value):
            return self._plain(asdict(value))
        if isinstance(value, SimpleNamespace):
            return self._plain(vars(value))
        if isinstance(value, dict):
            return {str(key): self._plain(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._plain(item) for item in value]
        if isinstance(value, date):
            return value.isoformat()
        return value
