from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "src" / "main.jsx"


def test_premarket_watchlist_is_not_hard_limited_to_five_items():
    source = MAIN.read_text(encoding="utf-8")

    assert "watchlist.slice(0, 5)" not in source
