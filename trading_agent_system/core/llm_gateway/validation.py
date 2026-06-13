from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class StructuredOutputValidationError(ValueError):
    pass


class StructuredOutputValidator:
    def validate(self, content: str, schema: Mapping[str, Any] | None) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise StructuredOutputValidationError(f"structured output is not valid JSON: {exc.msg}") from exc

        if not isinstance(parsed, dict):
            raise StructuredOutputValidationError("structured output must be a JSON object")

        required = list((schema or {}).get("required", []))
        missing = [key for key in required if key not in parsed]
        if missing:
            raise StructuredOutputValidationError(f"structured output missing required keys: {', '.join(missing)}")

        return parsed
