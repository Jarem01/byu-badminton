"""Parse the free-text partner field into structured PartnerHints.

Real examples this must handle (from the 2026 form):
- ``"Michael Pang"``                            -> one partner
- ``"Brain Chi; Hillary Kam"``                  -> two partners (typo 'Brain')
- ``"Yuen Yuen Chang(XD), Jarem Miller(MD)"``   -> per-event partners
- ``"Stanley Huang(mixed) Yuen Yuen Cheng (women)"`` -> two tagged, no comma
- ``"Simon or anyone else"``                    -> one name + 'flexible' prose
- ``"I don't have a partner:("`` / ``"idk"``    -> no usable name (prose)

Output is a list of PartnerHint (raw name + optional event hint). Resolution to
an actual player id happens later in ``fuzzy`` so this stays pure/testable.
"""

from __future__ import annotations

import re

from ..model.entities import PartnerHint
from .normalize import normalize_name

# Map hint tokens found in parentheses / words to an event code.
_HINT_MAP = {
    "xd": "XD", "mixed": "XD", "mix": "XD",
    "md": "MD",
    "wd": "WD", "women": "WD", "womens": "WD", "ladies": "WD",
    "ms": "MS",
    "ws": "WS",
    "men": "MD", "mens": "MD",
    "singles": None, "doubles": None,  # ambiguous words: recognized but no code
}

# Distinctive phrases signalling "no real partner named". These are long/unique
# enough to be safe as substrings.
_PROSE_PHRASES = (
    "anyone", "any one", "someone", "somebody", "random", "assign", "don't",
    "dont", "no partner", "n/a", "idk", "not sure", "whoever", "either",
    "willing", "select more than", "nobody", "unsure", "?",
)
# Short markers that must match as WHOLE words (so "na" doesn't hit "Anna").
_PROSE_TOKENS = {"na", "tbd", "tba", "none", "no", "nil"}

# name(hint) chunks, e.g. "Yuen Yuen Chang(XD)" or "Stanley Huang (mixed)"
_TAGGED_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]*?)\s*\(([^)]*)\)")
_PAREN_STRIP_RE = re.compile(r"\([^)]*\)")


def _hint_from_text(text: str) -> str | None:
    for tok in re.findall(r"[a-z]+", text.lower()):
        if tok in _HINT_MAP and _HINT_MAP[tok]:
            return _HINT_MAP[tok]
    return None


def looks_like_name(text: str) -> bool:
    """Heuristic: 1-4 alphabetic words, no prose markers, has a letter."""
    t = text.strip()
    if not t or not re.search(r"[A-Za-z]", t):
        return False
    low = t.lower()
    if any(phrase in low for phrase in _PROSE_PHRASES):
        return False
    if set(re.findall(r"[a-z']+", low)) & _PROSE_TOKENS:
        return False
    words = [w for w in re.split(r"\s+", t) if w]
    if not (1 <= len(words) <= 4):
        return False
    # Reject fragments that are mostly punctuation/non-letters.
    letters = sum(c.isalpha() for c in t)
    return letters >= max(2, len(t) // 2)


def _emit(name: str, hint: str | None, out: list[PartnerHint]) -> None:
    clean = normalize_name(name)
    # Strip a trailing " or ..." (e.g. "Simon or anyone else" -> "Simon").
    clean = re.split(r"\bor\b", clean, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if clean and looks_like_name(clean):
        out.append(PartnerHint(raw_name=clean, event_hint=hint))


def parse_partners(raw: str) -> list[PartnerHint]:
    if not raw:
        return []
    out: list[PartnerHint] = []
    # Strong separators = distinct partners.
    for piece in re.split(r"[;\n]+", raw):
        piece = piece.strip()
        if not piece:
            continue
        tagged = _TAGGED_RE.findall(piece)
        if len(tagged) >= 2:
            # Multiple "name(hint)" chunks in one piece (comma or space joined).
            for name, tag in tagged:
                _emit(name, _hint_from_text(tag), out)
            continue
        if len(tagged) == 1 and "," not in piece:
            name, tag = tagged[0]
            _emit(name, _hint_from_text(tag), out)
            continue
        # No reliable tags: fall back to comma splitting; parenthetical (if any)
        # becomes a shared/no hint per fragment.
        for frag in piece.split(","):
            frag = frag.strip()
            if not frag:
                continue
            hint = _hint_from_text(frag)
            name = _PAREN_STRIP_RE.sub("", frag).strip()
            _emit(name, hint, out)
    return out
