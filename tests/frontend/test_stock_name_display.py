from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"


def test_daily_strategy_displays_stock_name_instead_of_symbol_code():
    source = MAIN.read_text(encoding="utf-8")

    assert "formatStockDisplay(recommendation)" in source
    assert "formatStockDisplay(outcome)" in source
    assert "STOCK_NAME_MAP" in source
    assert "'600519.SH': '贵州茅台'" in source
    assert "formatStockName(symbol)" in source
