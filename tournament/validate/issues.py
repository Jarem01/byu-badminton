"""Validation issue type shared by the importer and the dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(slots=True)
class Issue:
    severity: Severity
    code: str
    message: str
    target: str = ""        # e.g. "row:5", "player:<id>", "pair:<id>"
    suggestion: str = ""
    # Structured payload for a note the page can act on, e.g. the players a
    # duplicate warning is about so it can offer to merge them.
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "severity": self.severity, "code": self.code, "message": self.message,
            "target": self.target, "suggestion": self.suggestion,
            "data": self.data,
        }
