from __future__ import annotations

import io

from scripts.run_premarket_agent import write_json_stdout


def test_write_json_stdout_handles_non_gbk_characters() -> None:
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="gbk")

    write_json_stdout({"title": "AI・芯片"}, stdout=stdout)
    stdout.flush()

    assert raw.getvalue().decode("utf-8") == '{\n  "title": "AI・芯片"\n}\n'
