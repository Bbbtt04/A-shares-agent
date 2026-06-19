from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"
API = ROOT / "web" / "src" / "api.js"


def test_daily_strategy_page_fetches_ledger_api_and_shows_learning_fields():
    main = MAIN.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")

    assert "fetchDailyStrategyLatest" in api
    assert "/api/daily-strategy/latest" in api
    assert "DailyStrategyPage" in main
    assert "dailyStrategy={dailyStrategy}" in main
    assert "每日策略" in main
    assert "因子贡献" in main
    assert "结算结果" in main
    assert "权重版本" in main


def test_daily_strategy_is_merged_under_one_pick_tab_and_visible_text_is_chinese():
    main = MAIN.read_text(encoding="utf-8")

    assert "activePage === 'daily-strategy'" not in main
    assert "setActivePage('daily-strategy')" not in main
    assert "Daily Strategy" not in main
    assert "Today Recommendation" not in main
    assert "Factor Contributions" not in main
    assert "Settlement" not in main
    assert "Weight Version" not in main
    assert "Loading daily strategy" not in main
    assert "JSON.stringify(learningUpdate || {}" not in main
    assert "JSON.stringify(outcome.attribution || {}" not in main


def test_daily_strategy_translates_actions_and_condition_sentences():
    main = MAIN.read_text(encoding="utf-8")

    assert "formatStrategyAction(recommendation.action" in main
    assert "formatStrategyText(item)" in main
    assert "观察" in main
    assert "开盘确认支持盘前因子信号" in main
    assert "移交前未出现新的放弃条件" in main
    assert "语义评审或新增证据否定催化逻辑" in main
