"""Schema adapters: turn raw CSV rows into Players + RegistrationEntries.

Two adapters flow through one pipeline so both today's messy Google-Form export
and a future strict one-submission-per-pair form can be ingested:

- ``LegacyFormAdapter``    -- the current 13-column form (needs fuzzy matching).
- ``StrictPairFormAdapter``-- a clean redesigned form (explicit gender/skill,
  one row per pair; no fuzzy matching needed).

Adapters ONLY produce data; fuzzy partner resolution and validation happen
downstream so this module stays pure and testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..model.entities import Player, RegistrationEntry, PartnerHint
from ..model.ids import IdFactory
from . import normalize as N
from .partner_parse import parse_partners


def _find_header(headers: list[str], *needles: str) -> str | None:
    """Return the first header containing any needle (case-insensitive)."""
    low = [(h, h.lower()) for h in headers]
    for needle in needles:
        n = needle.lower()
        for original, lowered in low:
            if n in lowered:
                return original
    return None


class SchemaAdapter(ABC):
    name: str

    @abstractmethod
    def detect(self, headers: list[str]) -> bool: ...

    @abstractmethod
    def build(self, rows: list[dict[str, str]], ids: IdFactory
              ) -> tuple[dict[str, Player], list[RegistrationEntry]]: ...


class LegacyFormAdapter(SchemaAdapter):
    name = "legacy"

    def detect(self, headers: list[str]) -> bool:
        return bool(
            _find_header(headers, "First Name")
            and _find_header(headers, "event")
            and _find_header(headers, "partner")
        )

    def build(self, rows, ids):
        h = lambda *n: _find_header(list(rows[0].keys()), *n) if rows else None
        c_first = h("First Name")
        c_last = h("Last Name")
        c_email = h("Email")
        c_weekend = h("weekends")
        c_weekday = h("evenings", "weekday")
        c_skill = h("Skill Level", "skill")
        c_events = h("What event", "event(s)", "event")
        c_haspartner = h("already have a partner")
        c_partner = h("full name")   # "...your partner's full name?"
        c_willing = h("willing to be assigned", "random partner")

        players: dict[str, Player] = {}
        regs: list[RegistrationEntry] = []
        for i, row in enumerate(rows):
            first = N.normalize_name(row.get(c_first, ""))
            last = N.normalize_name(row.get(c_last, ""))
            if not first and not last:
                continue  # blank row
            events = N.parse_events(row.get(c_events, ""))
            gender, _conflict = N.infer_gender_from_events(events)
            pid = ids.make("player", first, last)
            players[pid] = Player(
                id=pid, first=first, last=last,
                email=N.normalize_name(row.get(c_email, "")),
                gender=gender,
                skill=N.parse_skill(row.get(c_skill, "")),
                events=events,
                willing_random=bool(N.parse_yes_no(row.get(c_willing, ""), default=True)),
                weekend_avail=N.split_multi(row.get(c_weekend, "")),
                weekday_avail=N.split_multi(row.get(c_weekday, "")),
                source_row=i + 2,  # +2: header row is 1, data starts at 2
            )
            hints = parse_partners(row.get(c_partner, "") if c_partner else "")
            regs.append(RegistrationEntry(
                row_index=i + 2, player_id=pid, partner_hints=hints,
                raw={
                    "has_partner": row.get(c_haspartner, "") if c_haspartner else "",
                    "partner_raw": row.get(c_partner, "") if c_partner else "",
                },
            ))
        return players, regs


class StrictPairFormAdapter(SchemaAdapter):
    """For the redesigned form: one submission per entry, explicit fields.

    Expected headers (see docs/NEW_FORM_SPEC.md):
      Event, Club, Player 1 First/Last/Email/Gender/Skill,
      Player 2 First/Last/Email/Gender/Skill (blank for singles).
    """

    name = "strict"

    def detect(self, headers: list[str]) -> bool:
        return bool(_find_header(headers, "Player 1 First", "P1 First")
                    and _find_header(headers, "Event"))

    def build(self, rows, ids):
        keys = list(rows[0].keys()) if rows else []
        h = lambda *n: _find_header(keys, *n)
        c_event = h("Event")
        c_club = h("Club")
        c = {
            "p1_first": h("Player 1 First", "P1 First"),
            "p1_last": h("Player 1 Last", "P1 Last"),
            "p1_email": h("Player 1 Email", "P1 Email"),
            "p1_gender": h("Player 1 Gender", "P1 Gender"),
            "p1_skill": h("Player 1 Skill", "P1 Skill"),
            "p2_first": h("Player 2 First", "P2 First"),
            "p2_last": h("Player 2 Last", "P2 Last"),
            "p2_email": h("Player 2 Email", "P2 Email"),
            "p2_gender": h("Player 2 Gender", "P2 Gender"),
            "p2_skill": h("Player 2 Skill", "P2 Skill"),
        }

        def norm_gender(raw: str) -> str:
            s = (raw or "").strip().lower()
            if s.startswith("m"):
                return "M"
            if s.startswith("f") or s.startswith("w"):
                return "F"
            return "U"

        def infer_p2_gender(raw: str, event, p1_gender: str) -> str:
            """The clean form only asks Player 1's gender. Infer Player 2's from
            the event: mixed => opposite of P1; men's/women's doubles => same."""
            g = norm_gender(raw)
            if g != "U":
                return g
            if event == "XD":
                return "F" if p1_gender == "M" else ("M" if p1_gender == "F" else "U")
            if event == "MD":
                return "M"
            if event == "WD":
                return "F"
            return "U"

        players: dict[str, Player] = {}
        seen: dict[str, str] = {}       # dedupe key (email|name) -> player id
        regs: list[RegistrationEntry] = []

        def upsert(first, last, email, gender, skill, event, club, row_no) -> str:
            """Reuse one Player across rows (the form re-collects a person for a
            secondary event); accumulate events, fill missing gender/skill."""
            key = (email or f"{first}|{last}").strip().lower()
            if key in seen:
                p = players[seen[key]]
                if event and event not in p.events:
                    p.events.append(event)
                if p.gender == "U" and gender != "U":
                    p.gender = gender
                if p.skill is None and skill is not None:
                    p.skill = skill
                if not p.club and club:
                    p.club = club
                return seen[key]
            pid = ids.make("player", first, last)
            players[pid] = Player(id=pid, first=first, last=last, email=email,
                                  gender=gender, skill=skill,
                                  events=[event] if event else [], club=club,
                                  source_row=row_no)
            seen[key] = pid
            return pid

        for i, row in enumerate(rows):
            event = "".join(N.parse_events(row.get(c_event, "")) or [""])[:2] or None
            club = N.normalize_name(row.get(c_club, "")) if c_club else ""
            first = N.normalize_name(row.get(c["p1_first"], ""))
            last = N.normalize_name(row.get(c["p1_last"], ""))
            if not first and not last:
                continue
            p1_gender = norm_gender(row.get(c["p1_gender"], ""))
            pid = upsert(first, last, N.normalize_name(row.get(c["p1_email"], "")),
                         p1_gender, N.parse_skill(row.get(c["p1_skill"], "")),
                         event, club, i + 2)
            hints: list[PartnerHint] = []
            p2_first = N.normalize_name(row.get(c["p2_first"], "")) if c["p2_first"] else ""
            p2_last = N.normalize_name(row.get(c["p2_last"], "")) if c["p2_last"] else ""
            if p2_first or p2_last:
                pid2 = upsert(p2_first, p2_last,
                              N.normalize_name(row.get(c["p2_email"], "")),
                              infer_p2_gender(row.get(c["p2_gender"], ""), event, p1_gender),
                              N.parse_skill(row.get(c["p2_skill"], "")),
                              event, club, i + 2)
                hints.append(PartnerHint(raw_name=players[pid2].full,
                                         event_hint=event,
                                         resolved_player_id=pid2, confidence=1.0))
            regs.append(RegistrationEntry(row_index=i + 2, player_id=pid,
                                          partner_hints=hints,
                                          raw={"strict": "1", "club": club}))
        return players, regs


ADAPTERS: list[SchemaAdapter] = [StrictPairFormAdapter(), LegacyFormAdapter()]


def pick_adapter(headers: list[str], schema: str = "auto") -> SchemaAdapter:
    if schema and schema != "auto":
        for a in ADAPTERS:
            if a.name == schema:
                return a
        raise ValueError(f"Unknown schema {schema!r}")
    for a in ADAPTERS:
        if a.detect(headers):
            return a
    raise ValueError("Could not auto-detect a matching form schema from headers")
