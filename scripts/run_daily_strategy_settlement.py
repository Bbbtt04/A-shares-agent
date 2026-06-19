from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from trading_agent_system.agents.premarket_agent.daily_settlement import DailyStrategySettlementService
from trading_agent_system.agents.premarket_agent.factor_learning import (
    PremarketFactorLearningAgent,
    PremarketFactorLearningState,
)
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


class StaticOpenPriceProvider:
    def __init__(self, prices: dict[tuple[str, str], float]) -> None:
        self.prices = dict(prices)

    @classmethod
    def from_json_file(cls, path: str | Path | None) -> "StaticOpenPriceProvider":
        if path is None:
            return cls({})
        price_path = Path(path)
        if not price_path.exists():
            return cls({})
        payload = json.loads(price_path.read_text(encoding="utf-8"))
        prices: dict[tuple[str, str], float] = {}
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(value, dict):
                    for symbol, price in value.items():
                        prices[(str(key), str(symbol))] = float(price)
                elif "|" in str(key):
                    trading_day, symbol = str(key).split("|", 1)
                    prices[(trading_day, symbol)] = float(value)
        return cls(prices)

    def get_open_price(self, trading_day: date, symbol: str) -> float | None:
        return self.prices.get((trading_day.isoformat(), symbol))


class LedgerFactorWeightAdapter:
    def __init__(self, repository: object) -> None:
        self.repository = repository

    def load_active(self) -> PremarketFactorLearningState:
        active = self.repository.active()
        if not active:
            return PremarketFactorLearningState(version="pfl_initial")
        return PremarketFactorLearningState(
            version=str(active["version"]),
            factor_weights=dict(active.get("weights") or {}),
            sample_count=int((active.get("learning_summary") or {}).get("sample_count", 0)),
        )

    def save_new_active_version(self, update: object) -> None:
        next_state = getattr(update, "next_state")
        self.repository.save_version(
            {
                "version": next_state.version,
                "created_by_run_id": f"settlement_{next_state.version}",
                "previous_version": getattr(update, "previous_version", None),
                "is_active": True,
                "weights": dict(next_state.factor_weights),
                "learning_summary": {
                    **_plain_data(update),
                    "sample_count": next_state.sample_count,
                },
            }
        )


def run_daily_settlement(
    today: date,
    ledger_store: StrategyLedgerStore,
    *,
    price_provider: object | None = None,
    calendar: TradingCalendarService | None = None,
    learning_agent: object | None = None,
) -> dict[str, object]:
    service = DailyStrategySettlementService(
        calendar=calendar or TradingCalendarService(),
        recommendation_repository=ledger_store.recommendations,
        price_provider=price_provider or StaticOpenPriceProvider({}),
        price_repository=ledger_store.prices,
        outcome_repository=ledger_store.outcomes,
        learning_agent=learning_agent or PremarketFactorLearningAgent(),
        factor_weight_repository=LedgerFactorWeightAdapter(ledger_store.weights),
        audit_repository=ledger_store.audits,
    )
    result = service.settle(today)
    return _plain_data(result)


def _plain_data(value: object) -> Any:
    if is_dataclass(value):
        return _plain_data(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain_data(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {key: _plain_data(item) for key, item in vars(value).items() if not key.startswith("_")}
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle yesterday's daily strategy and persist learning to the ledger.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--db-path", default="data/daily_strategy.sqlite")
    parser.add_argument("--price-file", default=None)
    args = parser.parse_args()

    store = StrategyLedgerStore(args.db_path)
    try:
        result = run_daily_settlement(
            date.fromisoformat(args.date),
            store,
            price_provider=StaticOpenPriceProvider.from_json_file(args.price_file),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        store.close()


if __name__ == "__main__":
    main()
