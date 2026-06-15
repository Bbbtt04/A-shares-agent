from __future__ import annotations

from pydantic import ValidationError

from trading_agent_system.agents.one_pick_agent.schemas import (
    OnePickCandidate,
    OnePickOutcome,
    OnePickSelection,
    OnePickTradePlan,
)


def test_candidate_validates_confidence_and_positive_risk_reward():
    candidate = OnePickCandidate(
        symbol="688981.SH",
        name="SMIC",
        feature_scores={"catalyst_strength": 0.8},
        evidence_ids=["evt_1"],
        risk_flags=[],
        strategy_tags=["semiconductor"],
        source_rank=1,
        confidence=0.7,
        expected_upside_pct=0.05,
        expected_downside_pct=0.02,
        risk_reward_ratio=2.5,
    )

    assert candidate.symbol == "688981.SH"

    try:
        OnePickCandidate(
            symbol="688981.SH",
            feature_scores={},
            confidence=1.2,
            expected_upside_pct=0.03,
            expected_downside_pct=0.01,
            risk_reward_ratio=3.0,
        )
    except ValidationError as exc:
        assert "less than or equal to 1" in str(exc)
    else:
        raise AssertionError("invalid confidence should fail validation")


def test_selection_requires_selected_symbol():
    try:
        OnePickSelection(
            selected_symbol="",
            selected_name=None,
            score=0.7,
            confidence=0.7,
            risk_reward_ratio=2.0,
            threshold_passed=True,
            reasons=["best candidate"],
            evidence_ids=["evt_1"],
            risk_flags=[],
            feature_scores={},
        )
    except ValidationError as exc:
        assert "selected_symbol is required" in str(exc)
    else:
        raise AssertionError("empty selected symbol should fail validation")


def test_trade_plan_requires_buy_reason_and_positive_downside():
    try:
        OnePickTradePlan(
            symbol="688981.SH",
            name="SMIC",
            side="buy",
            quantity=100,
            confidence=0.7,
            expected_upside_pct=0.04,
            expected_downside_pct=0.0,
            risk_reward_ratio=2.0,
            entry_price=100.0,
            stop_loss_price=98.0,
            take_profit_price=104.0,
            buy_reasons=[],
            risk_reasons=["gap risk"],
            evidence_ids=["evt_1"],
        )
    except ValidationError as exc:
        message = str(exc)
        assert "expected_downside_pct" in message or "buy_reasons" in message
    else:
        raise AssertionError("trade plan without reasons/downside should fail validation")


def test_outcome_requires_entry_and_exit_price():
    try:
        OnePickOutcome(
            symbol="688981.SH",
            entry_price=100.0,
            exit_price=None,
            quantity=100,
            pnl_pct=0.02,
            max_favorable_excursion_pct=0.03,
            max_adverse_excursion_pct=-0.01,
            hit_take_profit=False,
            hit_stop_loss=False,
            direction_correct=True,
            selected_feature_scores={},
            tag_performance={},
        )
    except ValidationError as exc:
        assert "exit_price" in str(exc)
    else:
        raise AssertionError("outcome without exit price should fail validation")
