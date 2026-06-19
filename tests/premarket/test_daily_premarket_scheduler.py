from __future__ import annotations

import threading
import time
from datetime import date

from scripts.daily_premarket_scheduler import DailyJobResult, run_daily_jobs
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService


def test_run_daily_jobs_runs_recommendation_and_settlement_in_parallel() -> None:
    started = {"recommend": threading.Event(), "settle": threading.Event()}
    release = threading.Event()

    def recommend(trading_day: date) -> DailyJobResult:
        started["recommend"].set()
        assert started["settle"].wait(1)
        release.wait(1)
        return DailyJobResult(job="recommendation", status="success", payload={"day": trading_day.isoformat()})

    def settle(trading_day: date) -> DailyJobResult:
        started["settle"].set()
        assert started["recommend"].wait(1)
        release.wait(1)
        return DailyJobResult(job="settlement", status="success", payload={"day": trading_day.isoformat()})

    started_at = time.perf_counter()
    worker = threading.Thread(
        target=lambda: run_daily_jobs(
            date(2026, 6, 19),
            recommendation_runner=recommend,
            settlement_runner=settle,
            calendar=TradingCalendarService(trading_days=["2026-06-19"]),
        )
    )
    worker.start()
    assert started["recommend"].wait(1)
    assert started["settle"].wait(1)
    release.set()
    worker.join(1)

    assert not worker.is_alive()
    assert time.perf_counter() - started_at < 1


def test_run_daily_jobs_skips_non_trading_day() -> None:
    results = run_daily_jobs(
        date(2026, 6, 20),
        recommendation_runner=lambda _: DailyJobResult(job="recommendation", status="success", payload={}),
        settlement_runner=lambda _: DailyJobResult(job="settlement", status="success", payload={}),
        calendar=TradingCalendarService(trading_days=["2026-06-19"]),
    )

    assert [item.status for item in results] == ["skipped"]
    assert results[0].payload["reason"] == "non_trading_day"
