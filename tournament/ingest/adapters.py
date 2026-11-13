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
    """Return the matching header (case-insensitive).

    An exact match wins over a substring match, so ``"Gender"`` resolves to the
    player's own Gender column rather than ``"Partner's Gender"``.
    """
    low = [(h, h.lower()) for h in headers]
    for needle in needles:
        n = needle.lower()
        for original, lowered in low:
            if lowered == n:
                return original
    for needle in needles:
        n = needle.lower()
        for original, lowered in low:
            if n in lowered:
                return original
    return None


def _find_header_nth(headers: list[str], needle: str, n: int = 1) -> str | None:
    """The nth header containing ``needle`` (1-based). The real form repeats a
    whole question block (MD/WD partner, then XD partner), so the two columns
    are addressed by position."""
    hits = [h for h in headers if needle.lower() in h.lower()]
    return hits[n - 1] if len(hits) >= n else None


def _parse_gender(raw: str) -> str:
    """'Male'/'Female'/... -> M/F; anything else (incl. 'Prefer not to say') -> U."""
    s = (raw or "").strip().lower()
    if s.startswith("m"):
        return "M"
    if s.startswith("f") or s.startswith("w"):
        return "F"
    return "U"


def _either_yes(*values: str) -> bool:
    """True if any 'willing to be assigned a random partner' answer is yes.

    The form asks the question once per discipline; a blank answer (the other
    block) leaves the default, which is the historical behaviour (True).
    """
    answers = [N.parse_yes_no(v, default=None) for v in values]
    known = [a for a in answers if a is not None]
    return True if not known else any(known)


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
        keys = list(rows[0].keys()) if rows else []
        h = lambda *n: _find_header(keys, *n)
        c_first = h("First Name")
        c_last = h("Last Name")
        c_email = h("Email")
        c_gender = h("Gender")        # exact "Gender", not "Partner's Gender"
        c_weekend = h("weekends")
        c_weekday = h("evenings", "weekday")
        c_skill = h("Skill Level", "skill")
        c_events = h("What event", "event(s)", "event")
        c_haspartner = h("already have a partner")
        # The form repeats the partner block -- once for MD/WD, once for XD --
        # under identical question text (see source_csv's duplicate-header note).
        c_partner = _find_header_nth(keys, "full name", 1)
        c_partner_xd = _find_header_nth(keys, "full name", 2)
        c_willing = _find_header_nth(keys, "willing to be assigned", 1)
        c_willing_xd = _find_header_nth(keys, "willing to be assigned", 2)

        players: dict[str, Player] = {}
        regs: list[RegistrationEntry] = []
        for i, row in enumerate(rows):
            first = N.normalize_name(row.get(c_first, ""))
            last = N.normalize_name(row.get(c_last, ""))
            if not first and not last:
                continue  # blank row
            events = N.parse_events(row.get(c_events, ""))
            # Trust the gender the player stated; fall back to the gender implied
            # by their events when the answer is "Prefer not to say"/blank.
            gender, _conflict = N.infer_gender_from_events(events)
            declared = _parse_gender(row.get(c_gender, "")) if c_gender else "U"
            if declared != "U":
                gender = declared
            pid = ids.make("player", first, last)
            md_wd_event = next((e for e in ("MD", "WD") if e in events), None)
            # A player entered in a single doubles event who filled the first
            # partner block meant that event (XD-only players often answer there).
            default_ev = md_wd_event or (events[0] if len(events) == 1
                                         and events[0] in ("MD", "WD", "XD")
                                         else None)
            # Hints keep their column's meaning: the first block only names a
            # partner for MD/WD, the second only for XD. Both are kept even when
            # the player is not entered in that event -- a partner who named them
            # back is how a "forgot to tick the box" mismatch is detected (see
            # grouping._partner_confirmed).
            hints: list[PartnerHint] = []
            for hint in parse_partners(row.get(c_partner, "") if c_partner else ""):
                hint.event_hint = default_ev or hint.event_hint
                hints.append(hint)
            for hint in parse_partners(row.get(c_partner_xd, "") if c_partner_xd else ""):
                hint.event_hint = hint.event_hint or "XD"
                hints.append(hint)
            players[pid] = Player(
                id=pid, first=first, last=last,
                email=N.normalize_name(row.get(c_email, "")),
                gender=gender,
                skill=N.parse_skill(row.get(c_skill, "")),
                events=events,
                willing_random=_either_yes(
                    row.get(c_willing, "") if c_willing else "",
                    row.get(c_willing_xd, "") if c_willing_xd else ""),
                weekend_avail=N.split_multi(row.get(c_weekend, "")),
                weekday_avail=N.split_multi(row.get(c_weekday, "")),
                source_row=i + 2,  # +2: header row is 1, data starts at 2
            )
            regs.append(RegistrationEntry(
                row_index=i + 2, player_id=pid, partner_hints=hints,
                raw={
                    "has_partner": row.get(c_haspartner, "") if c_haspartner else "",
                    "partner_raw": row.get(c_partner, "") if c_partner else "",
                    "partner_xd_raw": (row.get(c_partner_xd, "")
                                       if c_partner_xd else ""),
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
