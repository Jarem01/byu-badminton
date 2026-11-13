"""Aggregate all validation rules into a single report."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model.entities import Tournament
from .issues import Issue
from .rules import ALL_RULES

_SEV_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def counts(self) -> dict:
        return {
            "error": len(self.errors),
            "warning": len(self.warnings),
            "info": sum(1 for i in self.issues if i.severity == "info"),
        }

    def as_dict(self) -> dict:
        return {"counts": self.counts(),
                "issues": [i.as_dict() for i in self.issues]}


def validate(t: Tournament, extra: list[Issue] | None = None) -> ValidationReport:
    issues: list[Issue] = list(extra or [])
    for rule in ALL_RULES:
        issues.extend(rule(t))
    issues.sort(key=lambda i: (_SEV_ORDER.get(i.severity, 3), i.code))
    return ValidationReport(issues=issues)
