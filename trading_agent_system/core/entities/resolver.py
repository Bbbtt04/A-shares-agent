from __future__ import annotations

from typing import Literal

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel


class SecurityEntity(StrictBaseModel):
    symbol: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    kind: Literal["stock", "fund", "index", "bond", "unknown"] = "unknown"
    market: Literal["SH", "SZ", "BJ", "UNKNOWN"] = "UNKNOWN"
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.symbol.split(".", 1)[0]


class EntityResolver:
    def __init__(self, entities: list[SecurityEntity] | None = None) -> None:
        self._by_symbol: dict[str, SecurityEntity] = {}
        self._by_lookup: dict[str, SecurityEntity] = {}
        self._by_code: dict[str, list[SecurityEntity]] = {}
        for entity in entities or []:
            self.register(entity)

    def register(self, entity: SecurityEntity) -> SecurityEntity:
        normalized = entity.model_copy(
            update={
                "symbol": entity.symbol.upper(),
                "market": self._market_from_symbol(entity.symbol),
            }
        )
        self._by_symbol[normalized.symbol] = normalized
        self._by_code.setdefault(normalized.code, []).append(normalized)
        self._index(normalized.symbol, normalized)
        self._index(normalized.code, normalized)
        self._index(normalized.name, normalized)
        for alias in normalized.aliases:
            self._index(alias, normalized)
        return normalized

    def resolve(self, query: str) -> SecurityEntity:
        key = self._normalize(query)
        direct = self._by_lookup.get(key)
        if direct is not None:
            return direct
        matches = self._by_code.get(key)
        if matches and len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"ambiguous security code: {query}")
        raise KeyError(f"unknown security entity: {query}")

    def _index(self, value: str, entity: SecurityEntity) -> None:
        self._by_lookup[self._normalize(value)] = entity

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().upper()

    @staticmethod
    def _market_from_symbol(symbol: str) -> str:
        parts = symbol.upper().split(".", 1)
        if len(parts) == 2 and parts[1] in {"SH", "SZ", "BJ"}:
            return parts[1]
        return "UNKNOWN"
