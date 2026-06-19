from __future__ import annotations

import sqlite3
from pathlib import Path

from trading_agent_system.core.strategy_ledger.repositories import (
    DecisionAuditRepository,
    FactorWeightRepository,
    OutcomeRepository,
    PriceRepository,
    RecommendationRepository,
    StrategyRunRepository,
)


class StrategyLedgerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._initialize_schema()

        self.runs = StrategyRunRepository(self.connection)
        self.recommendations = RecommendationRepository(self.connection)
        self.prices = PriceRepository(self.connection)
        self.outcomes = OutcomeRepository(self.connection)
        self.weights = FactorWeightRepository(self.connection)
        self.audits = DecisionAuditRepository(self.connection)

    def close(self) -> None:
        self.connection.close()

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_runs (
              id INTEGER PRIMARY KEY,
              run_id TEXT NOT NULL UNIQUE,
              trading_day TEXT NOT NULL,
              run_type TEXT NOT NULL,
              status TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              error_message TEXT,
              code_version TEXT,
              config_version TEXT,
              weight_version TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS premarket_events (
              id INTEGER PRIMARY KEY,
              event_id TEXT NOT NULL UNIQUE,
              run_id TEXT NOT NULL,
              trading_day TEXT NOT NULL,
              source_type TEXT NOT NULL,
              source_id TEXT,
              symbol TEXT,
              title TEXT NOT NULL,
              summary TEXT NOT NULL,
              theme TEXT,
              bias TEXT,
              confidence REAL,
              actionability TEXT,
              raw_payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS semantic_reviews (
              id INTEGER PRIMARY KEY,
              review_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              trading_day TEXT NOT NULL,
              symbol TEXT NOT NULL,
              theme TEXT,
              catalyst_relevance REAL NOT NULL,
              company_fit REAL NOT NULL,
              event_novelty REAL NOT NULL,
              evidence_consistency REAL NOT NULL,
              source_reliability REAL NOT NULL,
              crowding_risk REAL NOT NULL,
              stale_news_risk REAL NOT NULL,
              hype_risk REAL NOT NULL,
              semantic_verdict TEXT NOT NULL,
              positive_reasons_json TEXT NOT NULL,
              negative_reasons_json TEXT NOT NULL,
              evidence_ids_json TEXT NOT NULL,
              llm_model TEXT,
              llm_prompt_hash TEXT,
              llm_response_json TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS factor_scores (
              id INTEGER PRIMARY KEY,
              score_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              trading_day TEXT NOT NULL,
              symbol TEXT NOT NULL,
              signal_score REAL NOT NULL,
              confidence REAL NOT NULL,
              recommendation TEXT NOT NULL,
              factor_scores_json TEXT NOT NULL,
              factor_weights_json TEXT NOT NULL,
              factor_contributions_json TEXT NOT NULL,
              risk_flags_json TEXT NOT NULL,
              reasons_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS strategy_recommendations (
              id INTEGER PRIMARY KEY,
              recommendation_id TEXT NOT NULL UNIQUE,
              run_id TEXT NOT NULL,
              trading_day TEXT NOT NULL,
              symbol TEXT,
              action TEXT NOT NULL,
              priority INTEGER NOT NULL,
              confidence REAL NOT NULL,
              signal_score REAL NOT NULL,
              expected_risk_reward REAL,
              entry_conditions_json TEXT NOT NULL,
              avoid_conditions_json TEXT NOT NULL,
              risk_notes_json TEXT NOT NULL,
              handoff_payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS strategy_prices (
              id INTEGER PRIMARY KEY,
              trading_day TEXT NOT NULL,
              symbol TEXT NOT NULL,
              price_type TEXT NOT NULL,
              price_time TEXT NOT NULL,
              price REAL NOT NULL,
              source TEXT NOT NULL,
              raw_payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE (trading_day, symbol, price_type, price_time, source)
            );

            CREATE TABLE IF NOT EXISTS strategy_outcomes (
              id INTEGER PRIMARY KEY,
              outcome_id TEXT NOT NULL UNIQUE,
              recommendation_id TEXT NOT NULL,
              buy_trading_day TEXT NOT NULL,
              sell_trading_day TEXT NOT NULL,
              symbol TEXT NOT NULL,
              buy_price REAL,
              sell_price REAL,
              return_pct REAL,
              hit_result TEXT NOT NULL,
              outcome_label TEXT NOT NULL,
              attribution_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS factor_weight_versions (
              id INTEGER PRIMARY KEY,
              version TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              created_by_run_id TEXT NOT NULL,
              previous_version TEXT,
              is_active INTEGER NOT NULL,
              weights_json TEXT NOT NULL,
              learning_summary_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_audit_logs (
              id INTEGER PRIMARY KEY,
              audit_id TEXT NOT NULL UNIQUE,
              run_id TEXT NOT NULL,
              trading_day TEXT NOT NULL,
              symbol TEXT,
              stage TEXT NOT NULL,
              input_json TEXT NOT NULL,
              output_json TEXT NOT NULL,
              reasoning_summary TEXT NOT NULL,
              model_name TEXT,
              latency_ms REAL,
              created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()
