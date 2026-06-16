from trading_agent_system.agents.premarket_agent.recommendation_engine import PremarketRecommendationEngine
from trading_agent_system.schemas import PremarketCatalyst, PremarketReport, PremarketSourceStatus, PremarketTradePlan


def _plan(
    symbol: str,
    confidence: float,
    theme: str = "AI",
    risk_flags: list[str] | None = None,
) -> PremarketTradePlan:
    return PremarketTradePlan(
        symbol=symbol,
        name=f"name-{symbol}",
        theme=theme,
        action="watch",
        reason=f"{symbol} candidate",
        triggers=["auction confirmation"],
        risk_flags=risk_flags or [],
        confidence=confidence,
        reference_price=100.0,
        entry_low=99.0,
        entry_high=101.0,
        stop_loss=95.0,
        data_source="test",
    )


def _catalyst(symbol: str, source: str, confidence: float = 0.8, category: str = "quote_candidate") -> PremarketCatalyst:
    return PremarketCatalyst(
        title=f"{symbol} catalyst from {source}",
        category=category,
        bias="bullish",
        confidence=confidence,
        importance="A",
        sources=[source],
        symbols=[symbol],
        sectors=["AI"],
        summary="structured catalyst",
    )


def test_recommendation_engine_builds_risk_reward_price_plan_and_trace():
    engine = PremarketRecommendationEngine(strategy_version="test-v1")

    result = engine.build(
        watchlist=[_plan("688001.SH", confidence=0.95)],
        catalysts=[
            _catalyst("688001.SH", "a-stock-data/premarket"),
            _catalyst("688001.SH", "tonghuashun"),
        ],
    )

    recommendation = result.conservative[0]
    assert recommendation.symbol == "688001.SH"
    assert recommendation.mode == "conservative"
    assert recommendation.rating == "A"
    assert recommendation.price_plan.entry_low == 99.0
    assert recommendation.price_plan.entry_high == 101.0
    assert recommendation.price_plan.stop_loss == 95.0
    assert recommendation.price_plan.target_price_1 == 110.0
    assert recommendation.price_plan.target_price_2 == 114.0
    assert recommendation.price_plan.risk_reward_1 == 2.0
    assert recommendation.price_plan.risk_reward_2 == 2.8
    assert recommendation.price_plan.expected_r > 0
    assert recommendation.decision_trace["score_breakdown"]["source_confirmation"] > 0
    assert recommendation.decision_trace["evidence"][0]["source"] == "a-stock-data/premarket"


def test_recommendation_engine_splits_conservative_opportunity_and_watch_modes():
    engine = PremarketRecommendationEngine(strategy_version="test-v1")

    result = engine.build(
        watchlist=[
            _plan("688001.SH", confidence=0.95),
            _plan("300001.SZ", confidence=0.60),
            _plan("002001.SZ", confidence=0.55, risk_flags=["high_volatility"]),
        ],
        catalysts=[
            _catalyst("688001.SH", "a-stock-data/premarket"),
            _catalyst("688001.SH", "tonghuashun"),
            _catalyst("300001.SZ", "a-stock-data/premarket"),
            _catalyst("002001.SZ", "a-stock-data/premarket", confidence=0.6),
        ],
    )

    assert [item.symbol for item in result.conservative] == ["688001.SH"]
    assert [item.symbol for item in result.opportunity] == ["300001.SZ"]
    assert [item.symbol for item in result.watch] == ["002001.SZ"]


def test_recommendation_set_serializes_through_premarket_report():
    engine = PremarketRecommendationEngine(strategy_version="test-v1")
    recommendations = engine.build(
        watchlist=[_plan("688001.SH", confidence=0.95)],
        catalysts=[
            _catalyst("688001.SH", "a-stock-data/premarket"),
            _catalyst("688001.SH", "tonghuashun"),
        ],
    )

    report = PremarketReport(
        date="2026-06-14",
        window_start="2026-06-13T15:00:00+08:00",
        window_end="2026-06-14T09:30:00+08:00",
        market_view="neutral",
        summary="test",
        source_status=[PremarketSourceStatus(source="test", status="ok", fetched_count=1, used_count=1)],
        recommendations=recommendations,
    )

    payload = report.model_dump(mode="json")

    assert payload["recommendations"]["strategy_id"] == "premarket_rr_v1"
    assert payload["recommendations"]["conservative"][0]["price_plan"]["risk_reward_1"] == 2.0
