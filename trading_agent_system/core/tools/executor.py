from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import asdict, dataclass
from typing import Any

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.sandbox import (
    PermissionProfile,
    ToolPermissionError,
    ToolRateLimitError,
    ToolValidationError,
)

from .definition import ToolDefinition, ToolHandler
from .registry import ToolRegistry


@dataclass(frozen=True)
class ToolCallResult:
    tool_name: str
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
    fallback_used: bool = False
    cacheable: bool = False


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, audit_ledger: AuditLedger) -> None:
        self.registry = registry
        self.audit_ledger = audit_ledger
        self._call_times: dict[str, list[float]] = {}

    def call(
        self,
        tool_name: str,
        payload: dict[str, Any],
        permission_profile: PermissionProfile,
    ) -> ToolCallResult:
        definition = self.registry.get(tool_name)
        start = time.perf_counter()
        attempts = 0
        fallback_used = False

        try:
            self._check_permissions(definition, permission_profile)
            self._check_budget(permission_profile)
            self._check_rate_limit(definition, start)
            self._validate_required_fields(
                definition.input_schema,
                payload,
                schema_name="input",
            )

            last_error: Exception | None = None
            for _ in range(definition.retries + 1):
                attempts += 1
                try:
                    output = self._run_handler(
                        definition.handler,
                        payload,
                        definition.timeout_seconds,
                    )
                    self._validate_required_fields(
                        definition.output_schema,
                        output,
                        schema_name="output",
                    )
                    result = ToolCallResult(
                        tool_name=tool_name,
                        success=True,
                        output=output,
                        attempts=attempts,
                        elapsed_seconds=time.perf_counter() - start,
                        cacheable=definition.cacheable,
                    )
                    self._record_call(result, permission_profile)
                    return result
                except Exception as exc:  # noqa: BLE001 - tool failures are isolated
                    last_error = exc

            if definition.fallback is not None:
                fallback_used = True
                try:
                    output = self._run_handler(
                        definition.fallback,
                        payload,
                        definition.timeout_seconds,
                    )
                    self._validate_required_fields(
                        definition.output_schema,
                        output,
                        schema_name="output",
                    )
                    result = ToolCallResult(
                        tool_name=tool_name,
                        success=True,
                        output=output,
                        attempts=attempts,
                        elapsed_seconds=time.perf_counter() - start,
                        fallback_used=True,
                        cacheable=definition.cacheable,
                    )
                    self._record_call(result, permission_profile)
                    return result
                except Exception as exc:  # noqa: BLE001 - fallback failures are reported
                    last_error = exc

            result = ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=str(last_error) if last_error else "tool call failed",
                attempts=attempts,
                elapsed_seconds=time.perf_counter() - start,
                fallback_used=fallback_used,
                cacheable=definition.cacheable,
            )
            self._record_call(result, permission_profile)
            return result
        except (ToolPermissionError, ToolValidationError, ToolRateLimitError) as exc:
            result = ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
                attempts=attempts,
                elapsed_seconds=time.perf_counter() - start,
                fallback_used=fallback_used,
                cacheable=definition.cacheable,
            )
            self._record_call(result, permission_profile)
            raise

    def _check_permissions(
        self,
        definition: ToolDefinition,
        permission_profile: PermissionProfile,
    ) -> None:
        if permission_profile.allows_all(definition.required_permissions):
            return
        missing = sorted(
            permission.value
            for permission in definition.required_permissions
            if permission not in permission_profile.permissions
        )
        raise ToolPermissionError(
            f"profile {permission_profile.role!r} lacks permissions: {', '.join(missing)}"
        )

    def _check_budget(self, permission_profile: PermissionProfile) -> None:
        if permission_profile.can_call_tool():
            return
        raise ToolPermissionError(
            f"profile {permission_profile.role!r} exhausted tool call budget"
        )

    def _check_rate_limit(self, definition: ToolDefinition, now: float) -> None:
        if definition.rate_limit_per_minute is None:
            return
        window_start = now - 60
        recent = [
            timestamp
            for timestamp in self._call_times.get(definition.name, [])
            if timestamp >= window_start
        ]
        if len(recent) >= definition.rate_limit_per_minute:
            self._call_times[definition.name] = recent
            raise ToolRateLimitError(
                f"tool {definition.name!r} exceeded {definition.rate_limit_per_minute}/minute rate limit"
            )
        recent.append(now)
        self._call_times[definition.name] = recent

    def _validate_required_fields(
        self,
        schema: Mapping[str, Any],
        value: Mapping[str, Any],
        *,
        schema_name: str,
    ) -> None:
        required = schema.get("required", [])
        missing = [field for field in required if field not in value]
        if missing:
            raise ToolValidationError(
                f"{schema_name} missing required field(s): {', '.join(missing)}"
            )

    def _run_handler(
        self,
        handler: ToolHandler,
        payload: dict[str, Any],
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        if timeout_seconds is None:
            return handler(payload)

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(handler, payload)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            raise TimeoutError(f"tool timed out after {timeout_seconds} seconds") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _record_call(
        self,
        result: ToolCallResult,
        permission_profile: PermissionProfile,
    ) -> None:
        payload = asdict(result)
        payload["permission_profile"] = permission_profile.role
        payload["agent"] = permission_profile.agent
        payload["max_tool_calls"] = permission_profile.max_tool_calls
        payload["spent_tool_calls"] = permission_profile.spent_tool_calls
        self.audit_ledger.write("tool.call", payload)
