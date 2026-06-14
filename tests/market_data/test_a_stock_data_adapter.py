from trading_agent_system.core.market_data.a_stock_data import AStockDataAdapter


def test_a_stock_data_adapter_builds_theme_candidates_from_tencent_quotes():
    def fake_fetch(symbols: list[str]) -> list[dict[str, object]]:
        assert symbols == ["688981.SH", "002371.SZ"]
        return [
            {
                "symbol": "688981.SH",
                "name": "中芯国际",
                "price": 90.0,
                "previous_close": 88.0,
                "change_pct": 2.27,
                "limit_up": 105.6,
                "limit_down": 70.4,
                "vol_ratio": 1.8,
            },
            {
                "symbol": "002371.SZ",
                "name": "北方华创",
                "price": 400.0,
                "previous_close": 398.0,
                "change_pct": 0.5,
                "limit_up": 477.6,
                "limit_down": 318.4,
                "vol_ratio": 1.1,
            },
        ]

    adapter = AStockDataAdapter(
        quote_fetcher=fake_fetch,
        theme_symbols={"半导体": ["688981.SH", "002371.SZ"]},
    )

    candidates = adapter.candidates_for_theme("半导体", limit=2)

    assert [candidate.symbol for candidate in candidates] == ["688981.SH", "002371.SZ"]
    assert candidates[0].name == "中芯国际"
    assert candidates[0].reference_price == 90.0
    assert candidates[0].entry_low == 89.1
    assert candidates[0].entry_high == 91.8
    assert candidates[0].target_price == 94.5
    assert candidates[0].stop_loss == 87.3
    assert candidates[0].data_source == "a-stock-data/tencent"
