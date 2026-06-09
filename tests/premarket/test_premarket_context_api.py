from __future__ import annotations

import json

from trading_agent_system.api import app as api_module


def test_premarket_context_api_returns_latest_radar_context(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "PREMARKET_REPORT_DIR", tmp_path / "premarket")
    api_module.PREMARKET_REPORT_DIR.mkdir(parents=True)
    (api_module.PREMARKET_REPORT_DIR / "2026-06-10.json").write_text(
        json.dumps(
            {
                "date": "2026-06-10",
                "market_view": "neutral",
                "morning_brief": {"key_themes": ["机器人"], "watch_symbols": ["300750.SZ"]},
                "opening_radar": {"confirmed_themes": ["机器人"], "failed_themes": ["券商"]},
                "instruction": {
                    "items": [
                        {
                            "instruction_type": "require_confirmation",
                            "target": "ALL",
                            "reason": "等待竞价确认",
                            "source_ids": ["src_1"],
                            "expires_at": "2026-06-10T09:30:00+08:00",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = api_module.premarket_context_latest()

    assert response["context"]["confirmed_themes"] == ["机器人"]
    assert response["context"]["failed_themes"] == ["券商"]
    assert response["context"]["watch_symbols"] == ["300750.SZ"]
