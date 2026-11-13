"""Field normalization for messy form data.

Every function is total and defensive: junk in -> a defined "unknown" value out
(never an exception, never a fabricated value). Missing/invalid data becomes
``None``/``"U"`` so the validation layer can flag it for a human.
"""

from __future__ import annotations

import re

from ..config import EVENT_CODES, SKILL_MAX, SKILL_MIN

# Canonical order used everywhere so output is deterministic.
_EVENT_ORDER = {code: i for i, code in enumerate(EVENT_CODES)}
_EVENT_RE = re.compile(r"\((MS|WS|MD|WD|XD)\)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Trim and collapse internal whitespace. Casing is left as entered to
    avoid mangling names like ``En-Chi`` or ``McDonald``."""
    return _WS_RE.sub(" ", (raw or "").strip())


def name_key(raw: str) -> str:
    """Case/space-insensitive key for matching and dedup."""
    return _WS_RE.sub(" ", (raw or "").strip().lower())


def parse_skill(raw: str) -> int | None:
    """Self-rated 1..9. Returns None for blank/non-numeric/out-of-range."""
    if raw is None:
        return None
    m = re.search(r"-?\d+", str(raw))
    if not m:
        return None
    val = int(m.group())
    if SKILL_MIN <= val <= SKILL_MAX:
        return val
    return None


def parse_events(raw: str) -> list[str]:
    """Extract event codes from strings like
    ``"Men's Singles (MS), Mixed Doubles (XD)"``. Deduped, canonical order."""
    if not raw:
        return []
    found = {m.group(1).upper() for m in _EVENT_RE.finditer(raw)}
    return sorted(found, key=lambda c: _EVENT_ORDER[c])


def parse_yes_no(raw: str, default: bool | None = None) -> bool | None:
    if raw is None:
        return default
    s = raw.strip().lower()
    if not s:
        return default
    if s.startswith("y"):
        return True
    if s.startswith("n"):
        return False
    return default


def split_multi(raw: str) -> list[str]:
    """Split a comma-joined multi-select (availability) into trimmed parts."""
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def infer_gender_from_events(events: list[str]) -> tuple[str, bool]:
    """Derive gender from the events entered (not fabricated -- it's implied by
    what the player signed up for). Returns (gender, conflict).

    - Any of MS/MD  => male
    - Any of WS/WD  => female
    - Only XD       => unknown ('U')
    - Both men's and women's singles/doubles => conflict, gender 'U'
    """
    male = any(e in ("MS", "MD") for e in events)
    female = any(e in ("WS", "WD") for e in events)
    if male and female:
        return "U", True
    if male:
        return "M", False
    if female:
        return "F", False
    return "U", False  # only XD (or nothing) -> unknown
