from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from trading_agent_system.api import app as api_module


def test_run_job_forces_utf8_subprocess_io(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"title": "AI・芯片"}', stderr="")

    monkeypatch.setattr(api_module.subprocess, "run", fake_run)
    monkeypatch.setattr(api_module, "JOBS", {"premarket": ("premarket", ["scripts/run_premarket_agent.py"])})

    result = api_module._run_job("premarket", date(2026, 6, 14))

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert result.parsed == {"title": "AI・芯片"}
