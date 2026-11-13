"""Apply manual data corrections with an append-only audit trail.

Every change records old value, new value, actor, and reason. The engine never
silently rewrites data — corrections are explicit and logged (audit records are
appended, never modified or deleted).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import EVENT_CODES, SKILL_MAX, SKILL_MIN
from ..model.entities import Override, Tournament
from ..ingest.normalize import parse_events, parse_skill

# Whitelisted player fields an admin may override, with coercion.
_PLAYER_FIELDS = {
    "first": str, "last": str, "email": str, "club": str,
    "gender": "gender", "skill": "skill", "events": "events",
    "willing_random": "bool", "withdrawn": "bool",
}


def _coerce(kind, raw: str):
    if kind is str:
        return raw.strip()
    if kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")
    if kind == "skill":
        v = parse_skill(raw)
        if v is None:
            raise ValueError(f"Skill must be an integer {SKILL_MIN}-{SKILL_MAX}")
        return v
    if kind == "gender":
        g = raw.strip().upper()[:1] or "U"
        if g not in ("M", "F", "U"):
            raise ValueError("Gender must be M, F, or U")
        return g
    if kind == "events":
        evs = parse_events(raw) or [e.strip().upper() for e in raw.split(",") if e.strip()]
        bad = [e for e in evs if e not in EVENT_CODES]
        if bad:
            raise ValueError(f"Unknown event code(s): {', '.join(bad)}")
        return evs
    raise ValueError(f"Unsupported field kind {kind!r}")


def apply_override(t: Tournament, actor: str, target: str, field_name: str,
                   new_value: str, reason: str = "",
                   now: str | None = None) -> Override:
    kind_prefix, _, obj_id = target.partition(":")
    if kind_prefix != "player":
        raise ValueError(f"Only 'player:<id>' overrides are supported, got {target!r}")
    player = t.players.get(obj_id)
    if not player:
        raise ValueError(f"No such player {obj_id!r}")
    if field_name not in _PLAYER_FIELDS:
        raise ValueError(f"Field {field_name!r} is not overridable")

    coerced = _coerce(_PLAYER_FIELDS[field_name], new_value)
    old = getattr(player, field_name)
    setattr(player, field_name, coerced)
    # A stub that gets real skill+gender is no longer a placeholder.
    if player.is_stub and player.skill is not None and player.gender != "U":
        player.is_stub = False

    ts = now or datetime.now(timezone.utc).isoformat()
    return Override(ts=ts, actor=actor, target=target, field_name=field_name,
                    old_value=str(old), new_value=str(coerced), reason=reason)
