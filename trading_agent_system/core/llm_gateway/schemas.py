from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class StrictGatewayModel(BaseModel):
    model_config = {"extra": "forbid"}


class ModelMessage(StrictGatewayModel):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(StrictGatewayModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def fill_total_tokens(cls, data: Any) -> Any:
        if isinstance(data, dict) and "total_tokens" not in data:
            data = {
                **data,
                "total_tokens": int(data.get("prompt_tokens", 0)) + int(data.get("completion_tokens", 0)),
            }
        return data


class ModelRequest(StrictGatewayModel):
    messages: list[ModelMessage]
    model: str | None = None
    temperature: float | None = None
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(StrictGatewayModel):
    content: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider_name: str | None = None
    model: str | None = None
    elapsed_ms: float = 0
    structured_output: dict[str, Any] | None = None
    cache_hit: bool = False
