from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from trading_agent_system.api import app as api_module


def test_run_job_returns_failed_result_when_subprocess_times_out(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        raise api_module.subprocess.TimeoutExpired(
            command,
            timeout=kwargs["timeout"],
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(api_module.subprocess, "run", fake_run)
    monkeypatch.setattr(api_module, "JOBS", {"premarket": ("premarket", ["scripts/run_premarket_agent.py"])})

    result = api_module._run_job("premarket", date(2026, 6, 14))

    assert result.status == "failed"
    assert result.returncode == -1
    assert result.stdout == "partial stdout"
    assert "timed out after 300 seconds" in result.stderr
    assert "partial stderr" in result.stderr
    assert result.parsed is None


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
    assert captured["timeout"] == 300
    assert result.parsed == {"title": "AI・芯片"}
