from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Callable, Protocol
from urllib import request as urllib_request

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


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout: float = 30.0,
        transport: Transport | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self.transport = transport or self._default_transport

    def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError(f"api_key is required for provider '{self.provider_name}'")
        payload: dict[str, Any] = {
            "model": request.model or self.default_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        response = self.transport(
            f"{self.base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
            self.timeout,
        )
        content = self._content(response)
        usage = response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
        return ModelResponse(
            content=content,
            usage=TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
            ),
            provider_name=self.provider_name,
            model=str(response.get("model") or payload["model"]),
        )

    def _content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"provider '{self.provider_name}' returned no choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"provider '{self.provider_name}' returned invalid choice")
        message = first.get("message")
        if isinstance(message, dict) and message.get("content") is not None:
            return str(message["content"])
        if first.get("text") is not None:
            return str(first["text"])
        raise RuntimeError(f"provider '{self.provider_name}' returned no content")

    def _default_transport(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=timeout) as response:  # nosec B310 - user-configured LLM endpoint
            return json.loads(response.read().decode("utf-8"))
