from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from scripts.run_daily_premarket_recommendation import run_daily_recommendation
from scripts.run_daily_strategy_settlement import StaticOpenPriceProvider, run_daily_settlement
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


@dataclass(slots=True)
class DailyJobResult:
    job: str
    status: str
    payload: dict[str, object]


Runner = Callable[[date], DailyJobResult]


def run_daily_jobs(
    trading_day: date,
    *,
    recommendation_runner: Runner,
    settlement_runner: Runner,
    calendar: TradingCalendarService | None = None,
) -> list[DailyJobResult]:
    calendar = calendar or TradingCalendarService()
    if not calendar.is_trading_day(trading_day):
        return [DailyJobResult(job="daily_strategy", status="skipped", payload={"reason": "non_trading_day"})]

    results: list[DailyJobResult] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(recommendation_runner, trading_day),
            executor.submit(settlement_runner, trading_day),
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item.job)


def build_default_runners(
    *,
    report_dir: str | Path,
    db_path: str | Path,
    event_dir: str | Path,
    learning_dir: str | Path,
    price_file: str | Path | None,
    top_n: int,
) -> tuple[Runner, Runner]:
    def recommendation_runner(trading_day: date) -> DailyJobResult:
        store = StrategyLedgerStore(db_path)
        try:
            payload = run_daily_recommendation(
                Path(report_dir) / f"{trading_day.isoformat()}.json",
                store,
                event_dir=event_dir,
                learning_dir=learning_dir,
                top_n=top_n,
            )
            return DailyJobResult(job="recommendation", status=str(payload["status"]), payload=payload)
        finally:
            store.close()

    def settlement_runner(trading_day: date) -> DailyJobResult:
        store = StrategyLedgerStore(db_path)
        try:
            payload = run_daily_settlement(
                trading_day,
                store,
                price_provider=StaticOpenPriceProvider.from_json_file(price_file),
            )
            return DailyJobResult(job="settlement", status=str(payload["status"]), payload=payload)
        finally:
            store.close()

    return recommendation_runner, settlement_runner


def run_scheduler_loop(
    *,
    run_once: bool,
    poll_seconds: int,
    recommendation_time: str,
    settlement_time: str,
    runners: tuple[Runner, Runner],
    calendar: TradingCalendarService | None = None,
) -> list[DailyJobResult] | None:
    calendar = calendar or TradingCalendarService()
    if run_once:
        return run_daily_jobs(date.today(), recommendation_runner=runners[0], settlement_runner=runners[1], calendar=calendar)

    completed: set[tuple[str, date]] = set()
    while True:
        now = datetime.now(calendar.timezone)
        today = now.date()
        current_time = now.strftime("%H:%M")
        if calendar.is_trading_day(today):
            if current_time >= recommendation_time and ("recommendation", today) not in completed:
                runners[0](today)
                completed.add(("recommendation", today))
            if current_time >= settlement_time and ("settlement", today) not in completed:
                runners[1](today)
                completed.add(("settlement", today))
        time.sleep(poll_seconds)


def _plain(value: object) -> object:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily premarket recommendation and settlement jobs.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--recommendation-time", default="08:45")
    parser.add_argument("--settlement-time", default="09:31")
    parser.add_argument("--report-dir", default="reports/premarket")
    parser.add_argument("--db-path", default="data/daily_strategy.sqlite")
    parser.add_argument("--event-dir", default="data/events")
    parser.add_argument("--learning-dir", default="data/premarket_learning")
    parser.add_argument("--price-file", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    runners = build_default_runners(
        report_dir=args.report_dir,
        db_path=args.db_path,
        event_dir=args.event_dir,
        learning_dir=args.learning_dir,
        price_file=args.price_file,
        top_n=args.top_n,
    )
    result = run_scheduler_loop(
        run_once=args.once,
        poll_seconds=args.poll_seconds,
        recommendation_time=args.recommendation_time,
        settlement_time=args.settlement_time,
        runners=runners,
    )
    if result is not None:
        print(json.dumps(_plain(result), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
