from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from trading_agent_system.core.audit import AuditLedger

from .clients import ModelClient
from .prompts import PromptTemplateRegistry
from .schemas import ModelMessage, ModelRequest, ModelResponse
from .validation import StructuredOutputValidator


class LLMGatewayError(RuntimeError):
    pass


class LLMGateway:
    def __init__(
        self,
        clients: Mapping[str, ModelClient],
        audit_ledger: AuditLedger | None = None,
        prompt_templates: PromptTemplateRegistry | None = None,
        structured_validator: StructuredOutputValidator | None = None,
        pricing: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self.clients = dict(clients)
        self.audit_ledger = audit_ledger or AuditLedger()
        self.prompt_templates = prompt_templates or PromptTemplateRegistry()
        self.structured_validator = structured_validator or StructuredOutputValidator()
        self.pricing = {provider: dict(rates) for provider, rates in (pricing or {}).items()}
        self._cache: dict[str, ModelResponse] = {}

    def complete(
        self,
        *,
        messages: Sequence[ModelMessage] | None = None,
        prompt_template: str | None = None,
        variables: Mapping[str, Any] | None = None,
        route_order: Sequence[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        response_schema: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> ModelResponse:
        resolved_route = list(route_order or self.clients.keys())
        if not resolved_route:
            raise LLMGatewayError("route_order must include at least one model client")

        if cache_key is not None and cache_key in self._cache:
            cached = self._cache[cache_key].model_copy(update={"cache_hit": True, "elapsed_ms": 0})
            self._audit_success(cached, resolved_route, [], cache_hit=True)
            return cached

        request_messages = self._resolve_messages(messages, prompt_template, variables)
        request = ModelRequest(
            messages=request_messages,
            model=model,
            temperature=temperature,
            response_schema=dict(response_schema) if response_schema is not None else None,
            metadata=dict(metadata or {}),
        )

        started_at = perf_counter()
        failed_attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None

        for provider_name in resolved_route:
            client = self.clients.get(provider_name)
            if client is None:
                last_error = LLMGatewayError(f"model client '{provider_name}' is not registered")
                failed_attempts.append({"provider_name": provider_name, "attempt": 1, "error": str(last_error)})
                continue

            for attempt in (1, 2):
                try:
                    response = client.complete(request)
                    structured_output = None
                    if response_schema is not None:
                        structured_output = self.structured_validator.validate(response.content, response_schema)
                    elapsed_ms = (perf_counter() - started_at) * 1000
                    provider = response.provider_name or getattr(client, "provider_name", provider_name)
                    usage = self._usage_with_cost(response, provider)
                    final_response = response.model_copy(
                        update={
                            "provider_name": provider,
                            "elapsed_ms": elapsed_ms,
                            "usage": usage,
                            "structured_output": structured_output,
                        }
                    )
                    if cache_key is not None:
                        self._cache[cache_key] = final_response
                    self._audit_success(final_response, resolved_route, failed_attempts)
                    return final_response
                except Exception as exc:
                    last_error = exc
                    failed_attempts.append({"provider_name": provider_name, "attempt": attempt, "error": str(exc)})

        message = "all model clients failed"
        if last_error is not None:
            message = f"{message}: {last_error}"
        raise LLMGatewayError(message) from last_error

    def _resolve_messages(
        self,
        messages: Sequence[ModelMessage] | None,
        prompt_template: str | None,
        variables: Mapping[str, Any] | None,
    ) -> list[ModelMessage]:
        if prompt_template is not None:
            rendered = self.prompt_templates.render(prompt_template, variables or {})
            return [ModelMessage(role="user", content=rendered)]
        if messages is None:
            raise ValueError("messages or prompt_template is required")
        return list(messages)

    def _usage_with_cost(self, response: ModelResponse, provider_name: str) -> Any:
        pricing = self.pricing.get(provider_name, {})
        prompt_rate = float(pricing.get("prompt_per_1k", 0))
        completion_rate = float(pricing.get("completion_per_1k", 0))
        cost = (
            response.usage.prompt_tokens / 1000 * prompt_rate
            + response.usage.completion_tokens / 1000 * completion_rate
        )
        return response.usage.model_copy(update={"estimated_cost": cost})

    def _audit_success(
        self,
        response: ModelResponse,
        route_order: Sequence[str],
        failed_attempts: Sequence[dict[str, Any]],
        *,
        cache_hit: bool | None = None,
    ) -> None:
        hit = response.cache_hit if cache_hit is None else cache_hit
        self.audit_ledger.write(
            "llm.call",
            {
                "provider_name": response.provider_name,
                "model": response.model,
                "route_order": list(route_order),
                "failed_attempts": list(failed_attempts),
                "elapsed_ms": response.elapsed_ms,
                "cache_hit": hit,
                "usage": response.usage.model_dump(mode="json"),
                "usage_total": response.usage.total_tokens,
                "estimated_cost": response.usage.estimated_cost,
                "structured_output": response.structured_output,
            },
        )
