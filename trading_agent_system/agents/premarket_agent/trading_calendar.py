from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from premarket_contracts import FetchWindowContract

from .schemas import PreMarketWindow


DEFAULT_SESSION = {
    "previous_close_time": "15:00:00",
    "morning_brief_cutoff": "08:45:00",
    "auction_start": "09:15:00",
    "auction_observation_end": "09:20:00",
    "auction_confirm_start": "09:20:00",
    "auction_end": "09:25:00",
    "continuous_open": "09:30:00",
}


class TradingCalendarService:
    def __init__(
        self,
        timezone_name: str = "Asia/Shanghai",
        holidays: list[str] | None = None,
        extra_trading_days: list[str] | None = None,
        trading_days: list[str] | None = None,
        session: dict[str, str] | None = None,
    ) -> None:
        self.timezone_name = timezone_name
        self.timezone = ZoneInfo(timezone_name)
        self.holidays = {date.fromisoformat(item) for item in holidays or []}
        self.extra_trading_days = {date.fromisoformat(item) for item in extra_trading_days or []}
        self.trading_days = {date.fromisoformat(item) for item in trading_days or []}
        self.session = {**DEFAULT_SESSION, **(session or {})}

    @classmethod
    def from_config(cls, config: dict[str, object] | None) -> "TradingCalendarService":
        config = config or {}
        return cls(
            timezone_name=str(config.get("timezone", "Asia/Shanghai")),
            holidays=list(config.get("holidays", [])) if isinstance(config.get("holidays", []), list) else [],
            extra_trading_days=list(config.get("extra_trading_days", []))
            if isinstance(config.get("extra_trading_days", []), list)
            else [],
            trading_days=list(config.get("trading_days", [])) if isinstance(config.get("trading_days", []), list) else [],
            session=config.get("trading_session", {}) if isinstance(config.get("trading_session", {}), dict) else {},
        )

    def is_trading_day(self, value: date) -> bool:
        if self.trading_days:
            return value in self.trading_days
        if value in self.extra_trading_days:
            return True
        if value in self.holidays:
            return False
        return value.weekday() < 5

    def previous_trading_day(self, trading_day: date) -> date:
        current = trading_day - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def next_trading_day(self, trading_day: date) -> date:
        current = trading_day + timedelta(days=1)
        while not self.is_trading_day(current):
            current += timedelta(days=1)
        return current

    def build_window(self, trading_day: date) -> PreMarketWindow:
        previous = self.previous_trading_day(trading_day)
        return PreMarketWindow(
            trading_day=trading_day,
            previous_trading_day=previous,
            timezone=self.timezone_name,
            window_start=self._combine(previous, self.session["previous_close_time"]),
            morning_cutoff=self._combine(trading_day, self.session["morning_brief_cutoff"]),
            auction_start=self._combine(trading_day, self.session["auction_start"]),
            auction_observation_end=self._combine(trading_day, self.session["auction_observation_end"]),
            auction_confirm_start=self._combine(trading_day, self.session["auction_confirm_start"]),
            auction_end=self._combine(trading_day, self.session["auction_end"]),
            continuous_open=self._combine(trading_day, self.session["continuous_open"]),
        )

    def build_premarket_window(self, trading_day: date) -> PreMarketWindow:
        return self.build_window(trading_day)

    def build_fetch_window(
        self,
        trading_day: date,
        mode: Literal["premarket", "post_close"] = "premarket",
    ) -> FetchWindowContract:
        if mode == "premarket":
            window = self.build_window(trading_day)
            return FetchWindowContract(
                mode=mode,
                trading_day=window.trading_day,
                previous_trading_day=window.previous_trading_day,
                timezone=window.timezone,
                window_start=window.window_start,
                window_end=window.continuous_open,
            )

        next_day = self.next_trading_day(trading_day)
        next_window = self.build_window(next_day)
        return FetchWindowContract(
            mode=mode,
            trading_day=next_day,
            previous_trading_day=trading_day,
            timezone=self.timezone_name,
            window_start=self._combine(trading_day, self.session["previous_close_time"]),
            window_end=next_window.continuous_open,
        )

    def _combine(self, value: date, clock: str) -> datetime:
        parsed = time.fromisoformat(clock)
        return datetime.combine(value, parsed, tzinfo=self.timezone)
