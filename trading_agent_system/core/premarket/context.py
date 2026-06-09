from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel


BLOCK_NEW_ENTRY_TYPES = {
    "avoid_new_entry",
    "reduce_only",
    "block_until_official_confirmation",
}


class PremarketConstraint(StrictBaseModel):
    instruction_type: str
    target: str
    reason: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    requires_manual_review: bool = False

    def applies_to(self, symbol: str, themes: list[str] | None = None) -> bool:
        themes = themes or []
        target = self.target.strip()
        if target in {"ALL", "*"}:
            return True
        if target == symbol:
            return True
        if target.startswith("主题:") and target.removeprefix("主题:") in themes:
            return True
        return target in themes


class PremarketContext(StrictBaseModel):
    trading_day: date | None = None
    market_view: str = "neutral"
    key_themes: list[str] = Field(default_factory=list)
    confirmed_themes: list[str] = Field(default_factory=list)
    failed_themes: list[str] = Field(default_factory=list)
    watch_symbols: list[str] = Field(default_factory=list)
    avoid_symbols: list[str] = Field(default_factory=list)
    constraints: list[PremarketConstraint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_report(cls, report: object) -> "PremarketContext":
        data = _as_dict(report)
        instruction = _as_dict(data.get("instruction", {}))
        morning_brief = _as_dict(data.get("morning_brief", {}))
        opening_radar = _as_dict(data.get("opening_radar", {}))

        constraints = [
            PremarketConstraint.model_validate(item)
            for item in instruction.get("items", [])
            if isinstance(item, dict)
        ]

        watch_symbols = _unique(
            [
                *_symbols_from_trade_plans(data.get("watchlist", [])),
                *morning_brief.get("watch_symbols", []),
                *_symbols_from_radar_items(opening_radar.get("watch_items", [])),
                *[
                    constraint.target
                    for constraint in constraints
                    if constraint.instruction_type in {"watch_opening_auction", "increase_attention"}
                    and constraint.target not in {"ALL", "*"}
                    and not constraint.target.startswith("主题:")
                ],
            ]
        )
        avoid_symbols = _unique(
            [
                *_symbols_from_trade_plans(data.get("avoid_list", [])),
                *morning_brief.get("avoid_symbols", []),
                *_symbols_from_radar_items(opening_radar.get("risk_alerts", [])),
                *_symbols_from_radar_items(opening_radar.get("avoid_items", [])),
                *[
                    constraint.target
                    for constraint in constraints
                    if constraint.instruction_type in BLOCK_NEW_ENTRY_TYPES
                    and constraint.target not in {"ALL", "*"}
                    and not constraint.target.startswith("主题:")
                ],
            ]
        )

        return cls(
            trading_day=_parse_date(data.get("date") or data.get("trading_day") or instruction.get("trading_day")),
            market_view=str(data.get("market_view") or morning_brief.get("market_view") or "neutral"),
            key_themes=_unique([*morning_brief.get("key_themes", []), *_theme_names(morning_brief.get("top_themes", []))]),
            confirmed_themes=_unique(opening_radar.get("confirmed_themes", [])),
            failed_themes=_unique(opening_radar.get("failed_themes", [])),
            watch_symbols=watch_symbols,
            avoid_symbols=avoid_symbols,
            constraints=constraints,
            warnings=_unique([*data.get("warnings", []), *instruction.get("warnings", []), *opening_radar.get("warnings", [])]),
        )

    def constraints_for(self, symbol: str, themes: list[str] | None = None) -> list[PremarketConstraint]:
        return [constraint for constraint in self.constraints if constraint.applies_to(symbol, themes)]

    def blocks_new_entry(self, symbol: str, themes: list[str] | None = None) -> bool:
        if symbol in self.avoid_symbols:
            return True
        return any(constraint.instruction_type in BLOCK_NEW_ENTRY_TYPES for constraint in self.constraints_for(symbol, themes))

    def requires_confirmation(self, symbol: str, themes: list[str] | None = None) -> bool:
        return any(
            constraint.instruction_type == "require_confirmation" or constraint.requires_manual_review
            for constraint in self.constraints_for(symbol, themes)
        )

    def metadata_for(self, symbol: str, themes: list[str] | None = None) -> dict[str, Any]:
        matched = self.constraints_for(symbol, themes)
        evidence_ids = _unique([event_id for constraint in matched for event_id in constraint.evidence_event_ids])
        source_ids = _unique([source_id for constraint in matched for source_id in constraint.source_ids])
        return {
            "trading_day": self.trading_day.isoformat() if self.trading_day else None,
            "market_view": self.market_view,
            "matched_instruction_types": _unique([constraint.instruction_type for constraint in matched]),
            "reasons": _unique([constraint.reason for constraint in matched]),
            "evidence_ids": evidence_ids,
            "source_ids": source_ids,
            "requires_confirmation": self.requires_confirmation(symbol, themes),
            "blocks_new_entry": self.blocks_new_entry(symbol, themes),
            "key_themes": self.key_themes,
            "confirmed_themes": self.confirmed_themes,
            "failed_themes": self.failed_themes,
            "watch_symbols": self.watch_symbols,
            "avoid_symbols": self.avoid_symbols,
        }


class PremarketContextLoader:
    def __init__(self, report_dir: str | Path) -> None:
        self.report_dir = Path(report_dir)

    def load_latest(self) -> PremarketContext | None:
        reports = sorted(self.report_dir.glob("*.json"), reverse=True)
        if not reports:
            return None
        return self.load(reports[0])

    def load(self, path: str | Path) -> PremarketContext:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return PremarketContext.from_report(payload)


def _as_dict(value: object) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[attr-defined]
    return value if isinstance(value, dict) else {}


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


def _symbols_from_trade_plans(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item.get("symbol")) for item in value if isinstance(item, dict) and item.get("symbol")]


def _symbols_from_radar_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    symbols = []
    for item in value:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if symbol and not str(symbol).startswith("主题:"):
            symbols.append(str(symbol))
    return symbols


def _theme_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, dict) and item.get("theme_name"):
            names.append(str(item["theme_name"]))
    return names


def _unique(values: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
