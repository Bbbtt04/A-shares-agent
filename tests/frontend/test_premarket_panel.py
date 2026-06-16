from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"


def test_premarket_watchlist_is_not_hard_limited_to_five_items():
    source = MAIN.read_text(encoding="utf-8")

    assert "watchlist.slice(0, 5)" not in source


def test_premarket_panel_shows_recommendation_groups_and_risk_reward_fields():
    source = MAIN.read_text(encoding="utf-8")

    assert "今日荐股计划" in source
    assert "稳健型" in source
    assert "机会型" in source
    assert "观察型" in source
    assert "risk_reward_1" in source
    assert "expected_r" in source
