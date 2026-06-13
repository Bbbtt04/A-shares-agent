from datetime import date

from premarket_contracts import FetchWindowContract
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService


def test_premarket_window_uses_previous_trading_day_and_auction_end():
    service = TradingCalendarService()

    window = service.build_window(date(2026, 6, 8))

    assert window.previous_trading_day == date(2026, 6, 5)
    assert window.window_start.isoformat() == "2026-06-05T15:00:00+08:00"
    assert window.auction_end.isoformat() == "2026-06-08T09:25:00+08:00"


def test_premarket_window_skips_configured_holiday():
    service = TradingCalendarService(holidays=["2026-06-08"])

    window = service.build_window(date(2026, 6, 9))

    assert window.previous_trading_day == date(2026, 6, 5)


def test_calendar_exposes_spec_named_window_and_next_trading_day():
    service = TradingCalendarService(holidays=["2026-06-10"])

    window = service.build_premarket_window(date(2026, 6, 11))

    assert window.window_start.isoformat() == "2026-06-09T15:00:00+08:00"
    assert service.next_trading_day(date(2026, 6, 9)) == date(2026, 6, 11)


def test_calendar_builds_generic_fetch_windows_for_premarket_and_post_close():
    service = TradingCalendarService()

    premarket = service.build_fetch_window(date(2026, 6, 8), mode="premarket")
    post_close = service.build_fetch_window(date(2026, 6, 8), mode="post_close")

    assert isinstance(premarket, FetchWindowContract)
    assert premarket.mode == "premarket"
    assert premarket.window_start.isoformat() == "2026-06-05T15:00:00+08:00"
    assert premarket.window_end.isoformat() == "2026-06-08T09:30:00+08:00"
    assert post_close.mode == "post_close"
    assert post_close.previous_trading_day == date(2026, 6, 8)
    assert post_close.trading_day == date(2026, 6, 9)
    assert post_close.window_start.isoformat() == "2026-06-08T15:00:00+08:00"
    assert post_close.window_end.isoformat() == "2026-06-09T09:30:00+08:00"
