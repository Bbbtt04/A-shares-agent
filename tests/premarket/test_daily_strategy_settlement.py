from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest

from trading_agent_system.agents.premarket_agent.daily_settlement import DailyStrategySettlementService
from trading_agent_system.agents.premarket_agent.factor_learning import PremarketFactorLearningState
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


@dataclass(slots=True)
class FakeRecommendation:
    recommendation_id: str = "rec-1"
    trading_day: date = date(2026, 6, 18)
    symbol: str = "600001.SH"
    action: str = "buy"
    factor_scores: dict[str, float] | None = None
    risk_flags: list[str] | None = None


class FakeCalendar:
    def previous_trading_day(self, today: date) -> date:
        assert today == date(2026, 6, 19)
        return date(2026, 6, 18)


class FakeRecommendationRepository:
    def __init__(self, recommendation: FakeRecommendation | None) -> None:
        self.recommendation = recommendation
        self.days: list[date] = []

    def find_official(self, trading_day: date) -> FakeRecommendation | None:
        self.days.append(trading_day)
        return self.recommendation


class FakePriceRepository:
    def __init__(self, prices: dict[tuple[date, str, str], float | None] | None = None) -> None:
        self.prices = dict(prices or {})
        self.saved: list[SimpleNamespace] = []

    def get(self, trading_day: date, symbol: str, price_type: str) -> float | None:
        return self.prices.get((trading_day, symbol, price_type))

    def save(self, price: SimpleNamespace) -> None:
        self.saved.append(price)
        self.prices[(price.trading_day, price.symbol, price.price_type)] = price.price


class FakePriceProvider:
    def __init__(self, prices: dict[tuple[date, str], float | None] | None = None) -> None:
        self.prices = dict(prices or {})
        self.calls: list[tuple[date, str]] = []

    def get_open_price(self, trading_day: date, symbol: str) -> float | None:
        self.calls.append((trading_day, symbol))
        return self.prices.get((trading_day, symbol))


class FakeOutcomeRepository:
    def __init__(self) -> None:
        self.saved: list[SimpleNamespace] = []

    def save(self, outcome: SimpleNamespace) -> None:
        self.saved.append(outcome)


class FakeLearningAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[PremarketFactorLearningState, object]] = []

    def update(self, state: PremarketFactorLearningState, outcome_set: object) -> SimpleNamespace:
        self.calls.append((state, outcome_set))
        return SimpleNamespace(previous_version=state.version, next_state=state)


class FakeFactorWeightRepository:
    def __init__(self) -> None:
        self.active = PremarketFactorLearningState(
            version="pfl_20260618_000001",
            factor_weights={"catalyst_strength": 1.0},
            risk_penalties={},
            source_adjustments={},
            theme_adjustments={},
            llm_reliability={},
            sample_count=1,
        )
        self.saved: list[SimpleNamespace] = []

    def load_active(self) -> PremarketFactorLearningState:
        return self.active

    def save_new_active_version(self, update: SimpleNamespace) -> None:
        self.saved.append(update)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


def _service(
    recommendation: FakeRecommendation | None,
    repo_prices: dict[tuple[date, str, str], float | None] | None = None,
    provider_prices: dict[tuple[date, str], float | None] | None = None,
) -> tuple[
    DailyStrategySettlementService,
    FakeRecommendationRepository,
    FakePriceRepository,
    FakePriceProvider,
    FakeOutcomeRepository,
    FakeLearningAgent,
    FakeFactorWeightRepository,
    FakeAuditRepository,
]:
    recommendation_repository = FakeRecommendationRepository(recommendation)
    price_repository = FakePriceRepository(repo_prices)
    price_provider = FakePriceProvider(provider_prices)
    outcome_repository = FakeOutcomeRepository()
    learning_agent = FakeLearningAgent()
    factor_weight_repository = FakeFactorWeightRepository()
    audit_repository = FakeAuditRepository()
    return (
        DailyStrategySettlementService(
            calendar=FakeCalendar(),
            recommendation_repository=recommendation_repository,
            price_provider=price_provider,
            price_repository=price_repository,
            outcome_repository=outcome_repository,
            learning_agent=learning_agent,
            factor_weight_repository=factor_weight_repository,
            audit_repository=audit_repository,
        ),
        recommendation_repository,
        price_repository,
        price_provider,
        outcome_repository,
        learning_agent,
        factor_weight_repository,
        audit_repository,
    )


def test_settlement_skips_when_yesterday_has_no_official_recommendation() -> None:
    service, recommendations, prices, provider, outcomes, learning, weights, audit = _service(None)

    result = service.settle(date(2026, 6, 19))

    assert result.status == "skipped"
    assert result.yesterday == date(2026, 6, 18)
    assert recommendations.days == [date(2026, 6, 18)]
    assert provider.calls == []
    assert prices.saved == []
    assert outcomes.saved == []
    assert learning.calls == []
    assert weights.saved == []
    assert [entry["stage"] for entry in audit.logs] == ["settlement"]


def test_settlement_computes_return_uses_cached_price_and_saves_fetched_price() -> None:
    recommendation = FakeRecommendation(factor_scores={"catalyst_strength": 0.8}, risk_flags=["crowding"])
    service, _, prices, provider, outcomes, learning, weights, audit = _service(
        recommendation,
        repo_prices={(date(2026, 6, 18), "600001.SH", "buy_open"): 10.0},
        provider_prices={(date(2026, 6, 19), "600001.SH"): 10.5},
    )

    result = service.settle(date(2026, 6, 19))

    assert result.status == "success"
    assert result.outcome is outcomes.saved[0]
    assert result.outcome.buy_price == pytest.approx(10.0)
    assert result.outcome.sell_price == pytest.approx(10.5)
    assert result.outcome.return_pct == pytest.approx(0.05)
    assert result.outcome.hit_result == "win"
    assert provider.calls == [(date(2026, 6, 19), "600001.SH")]
    assert [(price.trading_day, price.price_type, price.price) for price in prices.saved] == [
        (date(2026, 6, 19), "sell_open", 10.5)
    ]
    assert len(learning.calls) == 1
    outcome_set = learning.calls[0][1]
    assert outcome_set.outcomes[0].factor_scores == {"catalyst_strength": 0.8}
    assert outcome_set.outcomes[0].risk_flags == ["crowding"]
    assert weights.saved == [result.learning_update]
    assert [entry["stage"] for entry in audit.logs] == ["settlement", "learning"]


def test_settlement_marks_pending_price_when_open_price_is_missing() -> None:
    service, _, _, provider, outcomes, learning, weights, audit = _service(
        FakeRecommendation(),
        repo_prices={(date(2026, 6, 18), "600001.SH", "buy_open"): 10.0},
        provider_prices={(date(2026, 6, 19), "600001.SH"): None},
    )

    result = service.settle(date(2026, 6, 19))

    assert result.status == "pending_price"
    assert result.outcome is outcomes.saved[0]
    assert result.outcome.buy_price == pytest.approx(10.0)
    assert result.outcome.sell_price is None
    assert result.outcome.return_pct is None
    assert result.outcome.hit_result == "pending_price"
    assert provider.calls == [(date(2026, 6, 19), "600001.SH")]
    assert learning.calls == []
    assert weights.saved == []
    assert [entry["stage"] for entry in audit.logs] == ["settlement"]


def test_settlement_records_watch_recommendation_but_does_not_learn() -> None:
    service, _, _, _, outcomes, learning, weights, audit = _service(
        FakeRecommendation(action="watch"),
        repo_prices={
            (date(2026, 6, 18), "600001.SH", "buy_open"): 10.0,
            (date(2026, 6, 19), "600001.SH", "sell_open"): 10.5,
        },
    )

    result = service.settle(date(2026, 6, 19))

    assert result.status == "success"
    assert result.outcome is outcomes.saved[0]
    assert result.outcome.hit_result == "win"
    assert learning.calls == []
    assert weights.saved == []
    assert [entry["stage"] for entry in audit.logs] == ["settlement", "learning"]
    assert audit.logs[-1]["output"]["status"] == "skipped"


def test_buy_recommendation_triggers_learning_and_persists_outcome() -> None:
    service, _, _, _, outcomes, learning, weights, _ = _service(
        FakeRecommendation(),
        repo_prices={
            (date(2026, 6, 18), "600001.SH", "buy_open"): 10.0,
            (date(2026, 6, 19), "600001.SH", "sell_open"): 9.97,
        },
    )

    result = service.settle(date(2026, 6, 19))

    assert result.status == "success"
    assert result.outcome.hit_result == "loss"
    assert result.outcome.return_pct == pytest.approx(-0.003)
    assert outcomes.saved == [result.outcome]
    assert len(learning.calls) == 1
    assert weights.saved == [result.learning_update]


def test_settlement_integrates_with_sqlite_strategy_ledger(tmp_path) -> None:
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    store.recommendations.save(
        {
            "recommendation_id": "rec-ledger",
            "run_id": "run-ledger",
            "trading_day": "2026-06-18",
            "symbol": "600001.SH",
            "action": "buy",
            "priority": 1,
            "confidence": 0.8,
            "signal_score": 0.7,
            "expected_risk_reward": 1.6,
            "entry_conditions": [],
            "avoid_conditions": [],
            "risk_notes": ["crowding"],
            "handoff_payload": {"factor_scores": {"catalyst_strength": 0.8}},
        }
    )
    store.prices.save(
        {
            "trading_day": "2026-06-18",
            "symbol": "600001.SH",
            "price_type": "buy_open",
            "price_time": "09:30",
            "price": 10.0,
            "source": "test",
            "raw_payload": {},
        }
    )
    service = DailyStrategySettlementService(
        calendar=FakeCalendar(),
        recommendation_repository=store.recommendations,
        price_provider=FakePriceProvider({(date(2026, 6, 19), "600001.SH"): 10.5}),
        price_repository=store.prices,
        outcome_repository=store.outcomes,
        learning_agent=FakeLearningAgent(),
        factor_weight_repository=FakeFactorWeightRepository(),
        audit_repository=store.audits,
    )

    result = service.settle(date(2026, 6, 19))

    assert result.status == "success"
    assert store.outcomes.by_recommendation("rec-ledger")[0]["return_pct"] == pytest.approx(0.05)
    assert store.prices.get("2026-06-19", "600001.SH", "sell_open")["price"] == pytest.approx(10.5)
    assert [entry["stage"] for entry in store.audits.by_run("settlement_2026-06-19")] == ["settlement", "learning"]
