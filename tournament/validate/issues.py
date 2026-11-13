"""Validation issue type shared by the importer and the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(slots=True)
class Issue:
    severity: Severity
    code: str
    message: str
    target: str = ""        # e.g. "row:5", "player:<id>", "pair:<id>"
    suggestion: str = ""

    def as_dict(self) -> dict:
        return {
            "severity": self.severity, "code": self.code, "message": self.message,
            "target": self.target, "suggestion": self.suggestion,
        }
