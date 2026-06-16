FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

COPY pyproject.toml README.md ./
COPY configs ./configs
COPY scripts ./scripts
COPY trading_agent_system ./trading_agent_system

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -e . \
    && mkdir -p \
        data/audit \
        data/config \
        data/events \
        data/metrics \
        data/runtime/checkpoints \
        data/strategy_learning \
        data/traces \
        reports/daily \
        reports/premarket

CMD ["sh", "-c", "uvicorn trading_agent_system.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
