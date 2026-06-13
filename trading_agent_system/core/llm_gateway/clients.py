from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from .schemas import ModelRequest, ModelResponse, TokenUsage


class ModelClient(Protocol):
    provider_name: str

    def complete(self, request: ModelRequest) -> ModelResponse:
        ...


class MockModelClient:
    def __init__(self, provider_name: str = "mock", outputs: Sequence[ModelResponse | Exception | str | dict[str, Any]] | None = None) -> None:
        self.provider_name = provider_name
        self._outputs = list(outputs or [])
        self.requests: list[ModelRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._outputs:
            raise RuntimeError(f"mock client '{self.provider_name}' has no outputs remaining")

        output = self._outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        if isinstance(output, ModelResponse):
            return output.model_copy(update={"provider_name": output.provider_name or self.provider_name})
        if isinstance(output, dict):
            return ModelResponse(
                content=json.dumps(output, ensure_ascii=False),
                usage=TokenUsage(),
                provider_name=self.provider_name,
            )
        return ModelResponse(content=output, usage=TokenUsage(), provider_name=self.provider_name)
