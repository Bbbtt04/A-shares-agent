from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from typing import Any


class PromptTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    template: str
    required_variables: tuple[str, ...]


class PromptTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}

    def register(self, name: str, template: str, required_variables: Sequence[str] | None = None) -> None:
        variables = tuple(required_variables or self._infer_variables(template))
        self._templates[name] = PromptTemplate(name=name, template=template, required_variables=variables)

    def render(self, name: str, variables: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
        if name not in self._templates:
            raise PromptTemplateError(f"prompt template '{name}' is not registered")

        template = self._templates[name]
        values = {**dict(variables or {}), **kwargs}
        missing = [variable for variable in template.required_variables if variable not in values]
        if missing:
            missing_text = ", ".join(missing)
            raise PromptTemplateError(f"prompt template '{name}' missing variables: {missing_text}")

        try:
            return template.template.format(**values)
        except KeyError as exc:
            missing_name = str(exc).strip("'")
            raise PromptTemplateError(f"prompt template '{name}' missing variables: {missing_name}") from exc

    def _infer_variables(self, template: str) -> list[str]:
        variables: list[str] = []
        for _, field_name, _, _ in Formatter().parse(template):
            if not field_name:
                continue
            variable = field_name.split(".", 1)[0].split("[", 1)[0]
            if variable not in variables:
                variables.append(variable)
        return variables
