from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _load(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class _Repository:
    json_fields: dict[str, str] = {}

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _row_to_dict(self, row: sqlite3.Row | None, *, include_id: bool = False) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        if not include_id:
            data.pop("id", None)
        for public_name, column_name in self.json_fields.items():
            if column_name in data:
                data[public_name] = _load(data.pop(column_name))
        return data

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self.connection.execute(sql, params).fetchone()
        return self._row_to_dict(row)

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows if row is not None]


class StrategyRunRepository(_Repository):
    json_fields = {"metadata": "metadata_json"}

    def start(
        self,
        run_id: str,
        trading_day: str,
        run_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = _now()
        self.connection.execute(
            """
            INSERT INTO strategy_runs (
              run_id, trading_day, run_type, status, started_at, metadata_json
            )
            VALUES (?, ?, ?, 'running', ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              trading_day = excluded.trading_day,
              run_type = excluded.run_type,
              status = 'running',
              started_at = excluded.started_at,
              finished_at = NULL,
              error_message = NULL,
              metadata_json = excluded.metadata_json
            """,
            (run_id, _iso(trading_day), run_type, started_at, _dump(metadata)),
        )
        self.connection.commit()
        row = self._fetch_one("SELECT * FROM strategy_runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise RuntimeError(f"strategy run was not saved: {run_id}")
        return row

    def finish(self, run_id: str, status: str, error_message: str | None = None) -> dict[str, Any]:
        self.connection.execute(
            """
            UPDATE strategy_runs
            SET status = ?, error_message = ?, finished_at = ?
            WHERE run_id = ?
            """,
            (status, error_message, _now(), run_id),
        )
        self.connection.commit()
        row = self._fetch_one("SELECT * FROM strategy_runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise ValueError(f"unknown strategy run: {run_id}")
        return row


class RecommendationRepository(_Repository):
    json_fields = {
        "entry_conditions": "entry_conditions_json",
        "avoid_conditions": "avoid_conditions_json",
        "risk_notes": "risk_notes_json",
        "handoff_payload": "handoff_payload_json",
    }

    def save(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        created_at = recommendation.get("created_at") or _now()
        self.connection.execute(
            """
            INSERT INTO strategy_recommendations (
              recommendation_id, run_id, trading_day, symbol, action, priority,
              confidence, signal_score, expected_risk_reward, entry_conditions_json,
              avoid_conditions_json, risk_notes_json, handoff_payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recommendation_id) DO UPDATE SET
              run_id = excluded.run_id,
              trading_day = excluded.trading_day,
              symbol = excluded.symbol,
              action = excluded.action,
              priority = excluded.priority,
              confidence = excluded.confidence,
              signal_score = excluded.signal_score,
              expected_risk_reward = excluded.expected_risk_reward,
              entry_conditions_json = excluded.entry_conditions_json,
              avoid_conditions_json = excluded.avoid_conditions_json,
              risk_notes_json = excluded.risk_notes_json,
              handoff_payload_json = excluded.handoff_payload_json,
              created_at = excluded.created_at
            """,
            (
                recommendation["recommendation_id"],
                recommendation["run_id"],
                _iso(recommendation["trading_day"]),
                recommendation.get("symbol"),
                recommendation["action"],
                recommendation["priority"],
                recommendation["confidence"],
                recommendation["signal_score"],
                recommendation.get("expected_risk_reward"),
                _dump(recommendation.get("entry_conditions", [])),
                _dump(recommendation.get("avoid_conditions", [])),
                _dump(recommendation.get("risk_notes", [])),
                _dump(recommendation.get("handoff_payload", {})),
                created_at,
            ),
        )
        self.connection.commit()
        row = self._fetch_one(
            "SELECT * FROM strategy_recommendations WHERE recommendation_id = ?",
            (recommendation["recommendation_id"],),
        )
        if row is None:
            raise RuntimeError("recommendation was not saved")
        return row

    def latest(self, trading_day: str | None = None) -> dict[str, Any] | None:
        if trading_day is None:
            return self._fetch_one(
                "SELECT * FROM strategy_recommendations ORDER BY trading_day DESC, created_at DESC, id DESC LIMIT 1",
                (),
            )
        return self._fetch_one(
            """
            SELECT * FROM strategy_recommendations
            WHERE trading_day = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (_iso(trading_day),),
        )

    def by_day(self, trading_day: str) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT * FROM strategy_recommendations
            WHERE trading_day = ?
            ORDER BY priority ASC, created_at DESC, id DESC
            """,
            (trading_day,),
        )

    def load_official_buy(self, trading_day: str) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT * FROM strategy_recommendations
            WHERE trading_day = ? AND action = 'buy'
            ORDER BY priority ASC, created_at DESC, id DESC
            LIMIT 1
            """,
            (_iso(trading_day),),
        )


class PriceRepository(_Repository):
    json_fields = {"raw_payload": "raw_payload_json"}

    def save(self, price: dict[str, Any]) -> dict[str, Any]:
        created_at = price.get("created_at") or _now()
        price_time = price.get("price_time", "09:30")
        self.connection.execute(
            """
            INSERT INTO strategy_prices (
              trading_day, symbol, price_type, price_time, price, source,
              raw_payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trading_day, symbol, price_type, price_time, source) DO UPDATE SET
              price = excluded.price,
              raw_payload_json = excluded.raw_payload_json,
              created_at = excluded.created_at
            """,
            (
                _iso(price["trading_day"]),
                price["symbol"],
                price["price_type"],
                price_time,
                price["price"],
                price["source"],
                _dump(price.get("raw_payload", {})),
                created_at,
            ),
        )
        self.connection.commit()
        row = self.get(_iso(price["trading_day"]), price["symbol"], price["price_type"], price_time)
        if row is None:
            raise RuntimeError("price was not saved")
        return row

    def get(
        self,
        trading_day: str,
        symbol: str,
        price_type: str,
        price_time: str = "09:30",
    ) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT * FROM strategy_prices
            WHERE trading_day = ? AND symbol = ? AND price_type = ? AND price_time = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (_iso(trading_day), symbol, price_type, price_time),
        )


class OutcomeRepository(_Repository):
    json_fields = {"attribution": "attribution_json"}

    def save(self, outcome: dict[str, Any]) -> dict[str, Any]:
        created_at = outcome.get("created_at") or _now()
        self.connection.execute(
            """
            INSERT INTO strategy_outcomes (
              outcome_id, recommendation_id, buy_trading_day, sell_trading_day,
              symbol, buy_price, sell_price, return_pct, hit_result,
              outcome_label, attribution_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(outcome_id) DO UPDATE SET
              recommendation_id = excluded.recommendation_id,
              buy_trading_day = excluded.buy_trading_day,
              sell_trading_day = excluded.sell_trading_day,
              symbol = excluded.symbol,
              buy_price = excluded.buy_price,
              sell_price = excluded.sell_price,
              return_pct = excluded.return_pct,
              hit_result = excluded.hit_result,
              outcome_label = excluded.outcome_label,
              attribution_json = excluded.attribution_json,
              created_at = excluded.created_at
            """,
            (
                outcome["outcome_id"],
                outcome["recommendation_id"],
                _iso(outcome["buy_trading_day"]),
                _iso(outcome["sell_trading_day"]),
                outcome["symbol"],
                outcome.get("buy_price"),
                outcome.get("sell_price"),
                outcome.get("return_pct"),
                outcome["hit_result"],
                outcome["outcome_label"],
                _dump(outcome.get("attribution", {})),
                created_at,
            ),
        )
        self.connection.commit()
        row = self._fetch_one("SELECT * FROM strategy_outcomes WHERE outcome_id = ?", (outcome["outcome_id"],))
        if row is None:
            raise RuntimeError("outcome was not saved")
        return row

    def by_recommendation(self, recommendation_id: str) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT * FROM strategy_outcomes
            WHERE recommendation_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (recommendation_id,),
        )

    def latest(self) -> dict[str, Any] | None:
        return self._fetch_one(
            "SELECT * FROM strategy_outcomes ORDER BY sell_trading_day DESC, created_at DESC, id DESC LIMIT 1",
            (),
        )


class FactorWeightRepository(_Repository):
    json_fields = {
        "weights": "weights_json",
        "learning_summary": "learning_summary_json",
    }

    def save_version(self, version: dict[str, Any]) -> dict[str, Any]:
        created_at = version.get("created_at") or _now()
        is_active = 1 if version.get("is_active") else 0
        if is_active:
            self.connection.execute("UPDATE factor_weight_versions SET is_active = 0")
        self.connection.execute(
            """
            INSERT INTO factor_weight_versions (
              version, created_at, created_by_run_id, previous_version, is_active,
              weights_json, learning_summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(version) DO UPDATE SET
              created_at = excluded.created_at,
              created_by_run_id = excluded.created_by_run_id,
              previous_version = excluded.previous_version,
              is_active = excluded.is_active,
              weights_json = excluded.weights_json,
              learning_summary_json = excluded.learning_summary_json
            """,
            (
                version["version"],
                created_at,
                version["created_by_run_id"],
                version.get("previous_version"),
                is_active,
                _dump(version.get("weights", {})),
                _dump(version.get("learning_summary", {})),
            ),
        )
        self.connection.commit()
        row = self._fetch_one("SELECT * FROM factor_weight_versions WHERE version = ?", (version["version"],))
        if row is None:
            raise RuntimeError("weight version was not saved")
        return row

    def active(self) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            SELECT * FROM factor_weight_versions
            WHERE is_active = 1
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (),
        )

    def activate(self, version: str) -> dict[str, Any]:
        existing = self._fetch_one("SELECT * FROM factor_weight_versions WHERE version = ?", (version,))
        if existing is None:
            raise ValueError(f"unknown factor weight version: {version}")
        self.connection.execute("UPDATE factor_weight_versions SET is_active = 0")
        self.connection.execute("UPDATE factor_weight_versions SET is_active = 1 WHERE version = ?", (version,))
        self.connection.commit()
        row = self.active()
        if row is None:
            raise RuntimeError("factor weight activation failed")
        return row


class DecisionAuditRepository(_Repository):
    json_fields = {
        "input": "input_json",
        "output": "output_json",
    }

    def log(self, audit: dict[str, Any]) -> dict[str, Any]:
        created_at = audit.get("created_at") or _now()
        self.connection.execute(
            """
            INSERT INTO decision_audit_logs (
              audit_id, run_id, trading_day, symbol, stage, input_json,
              output_json, reasoning_summary, model_name, latency_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(audit_id) DO UPDATE SET
              run_id = excluded.run_id,
              trading_day = excluded.trading_day,
              symbol = excluded.symbol,
              stage = excluded.stage,
              input_json = excluded.input_json,
              output_json = excluded.output_json,
              reasoning_summary = excluded.reasoning_summary,
              model_name = excluded.model_name,
              latency_ms = excluded.latency_ms,
              created_at = excluded.created_at
            """,
            (
                audit["audit_id"],
                audit["run_id"],
                _iso(audit["trading_day"]),
                audit.get("symbol"),
                audit["stage"],
                _dump(audit.get("input", {})),
                _dump(audit.get("output", {})),
                audit["reasoning_summary"],
                audit.get("model_name"),
                audit.get("latency_ms"),
                created_at,
            ),
        )
        self.connection.commit()
        row = self._fetch_one("SELECT * FROM decision_audit_logs WHERE audit_id = ?", (audit["audit_id"],))
        if row is None:
            raise RuntimeError("audit log was not saved")
        return row

    def by_run(self, run_id: str) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            SELECT * FROM decision_audit_logs
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        )
