"""Cross-entity data-quality rules. Each rule is a small function returning
Issues, so rules are independently testable and easy to extend.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ..config import DOUBLES_EVENTS
from ..engine.grouping import partner_confirmed
from ..ingest.normalize import infer_gender_from_events, name_key
from ..model.entities import Tournament
from .issues import Issue


def check_skill(t: Tournament) -> list[Issue]:
    out = []
    for p in t.players.values():
        if p.is_stub or not p.events:
            continue
        if p.skill is None:
            out.append(Issue("warning", "missing_skill",
                              f"{p.full} has no valid skill level (1-9).",
                              target=f"player:{p.id}"))
    return out


def check_gender(t: Tournament) -> list[Issue]:
    out = []
    for p in t.players.values():
        if not p.events:
            continue
        _, conflict = infer_gender_from_events(p.events)
        if conflict:
            out.append(Issue("error", "gender_event_conflict",
                             f"{p.full} is entered in both men's and women's "
                             f"events ({', '.join(p.events)}).",
                             target=f"player:{p.id}"))
        elif p.gender == "U" and not p.is_stub:
            out.append(Issue("warning", "unknown_gender",
                             f"{p.full}'s gender is unknown "
                             f"(only Mixed Doubles entered) — set it manually.",
                             target=f"player:{p.id}"))
    return out


def _name_parts(p) -> tuple[str, str]:
    bits = name_key(p.full).split()
    return (bits[0], " ".join(bits[1:])) if bits else ("", "")


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _near_name(a, b) -> bool:
    """Do two names look like the same person typed twice? "Amy Ngyun" and
    "Amy Nguyen" do; "Josh Lim" and "Josh Liu" do not."""
    af, al = _name_parts(a)
    bf, bl = _name_parts(b)
    if not af or not bf:
        return False
    if al and bl:
        # "Ngyun" for "Nguyen" is 0.73; "Lim" for "Liu" is 0.67 and is a
        # different person, so 0.7 with the same initial is a fair line.
        return (_ratio(af, bf) >= 0.8 and _ratio(al, bl) >= 0.7
                and al[0] == bl[0])
    return _ratio(name_key(a.full), name_key(b.full)) >= 0.9


def _people(t: Tournament, ids: list[str]) -> list[dict]:
    """The players a duplicate note is about, for the page's merge buttons."""
    return [{"id": i, "name": t.players[i].full,
             "email": getattr(t.players[i], "email", "") or ""} for i in ids]


def check_duplicates(t: Tournament) -> list[Issue]:
    out = []
    by_email: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for p in t.players.values():
        if p.is_stub:
            continue
        if p.email:
            by_email.setdefault(p.email.lower(), []).append(p.id)
        by_name.setdefault(name_key(p.full), []).append(p.id)
    for email, ids in by_email.items():
        if len(ids) > 1:
            names = ", ".join(t.players[i].full for i in ids)
            out.append(Issue("warning", "duplicate_email",
                             f"Duplicate registration email {email}: {names}.",
                             target=f"player:{ids[0]}",
                             data={"players": _people(t, ids)}))
    for _key, ids in by_name.items():
        if len(ids) > 1 and not any(t.players[i].email for i in ids):
            out.append(Issue("warning", "duplicate_name",
                             f"Possible duplicate registrations for "
                             f"{t.players[ids[0]].full}.",
                             target=f"player:{ids[0]}",
                             data={"players": _people(t, ids)}))

    # Nearly the same name: the typo'd second row that an exact match misses.
    already = {frozenset(ids) for ids in by_email.values() if len(ids) > 1}
    already |= {frozenset(ids) for ids in by_name.values() if len(ids) > 1}

    # One bucket per spelled name, in name order (id order inside a bucket), so
    # the same roster always produces the same groups -- two entries spelled
    # identically always end up in the same group rather than pairing the typo
    # with whichever of them happened to be read first.
    buckets: dict[str, list] = {}
    for p in sorted(t.players.values(), key=lambda x: (name_key(x.full), x.id)):
        key = name_key(p.full)
        if key:
            buckets.setdefault(key, []).append(p)
    keys = sorted(buckets)
    used: set[str] = set()
    for i, key in enumerate(keys):
        if key in used:
            continue
        group = list(buckets[key])          # every entry spelt this way
        for other in keys[i + 1:]:
            if other in used:
                continue
            if _near_name(group[0], buckets[other][0]):
                group.extend(buckets[other])
                used.add(other)
        if len(group) < 2:
            continue
        ids = [p.id for p in group]
        if frozenset(ids) in already:
            continue                    # the exact rules already said this
        used.add(key)
        shown: list[str] = []
        for p in group:
            label = f"'{p.full}'" + (" (placeholder)" if p.is_stub else "")
            n = sum(1 for q in group
                    if q.full == p.full and q.is_stub == p.is_stub)
            label += f" ×{n}" if n > 1 else ""
            if label not in shown:
                shown.append(label)
        out.append(Issue("warning", "similar_name",
                         "Possible duplicate registrations: " +
                         " and ".join(shown) +
                         " — the names look almost the same.",
                         target=f"player:{ids[0]}",
                         data={"players": _people(t, ids)}))
    return out


def _resolved_partner_edges(t: Tournament):
    """Yield (player_id, partner_id, event_hint) for resolved hints."""
    reg_by_player = {r.player_id: r for r in t.registrations}
    for r in t.registrations:
        for h in r.partner_hints:
            if h.resolved_player_id:
                yield r.player_id, h.resolved_player_id, h.event_hint
    return reg_by_player


def check_partners(t: Tournament) -> list[Issue]:
    out = []
    reg_by_player = {r.player_id: r for r in t.registrations}
    # A partner named by someone else counts too: the pairing step honours the
    # request from either side, so "X needs a partner" would be wrong for a
    # player who is about to be paired because their partner named them.
    inbound = {(h.resolved_player_id, h.event_hint)
               for r in t.registrations for h in r.partner_hints
               if h.resolved_player_id and h.event_hint
               and partner_confirmed(t, r.player_id, h.resolved_player_id,
                                     h.event_hint)}

    for r in t.registrations:
        p = t.players.get(r.player_id)
        if not p:
            continue
        paired_events = {pr.event for pr in t.pairs.values()
                        if p.id in pr.player_ids}
        resolved_events = set()
        has_generic = False
        for h in r.partner_hints:
            if not h.resolved_player_id:
                continue
            if not h.event_hint:
                has_generic = True
            elif partner_confirmed(t, p.id, h.resolved_player_id, h.event_hint):
                # A request the pairing step refuses (partner not entered, not
                # mutual) must not hide the fact that this player still needs
                # a partner.
                resolved_events.add(h.event_hint)
        for ev in [e for e in p.events if e in DOUBLES_EVENTS]:
            if (ev in resolved_events or has_generic or ev in paired_events
                    or (p.id, ev) in inbound):
                continue
            if p.willing_random:
                out.append(Issue("info", "needs_random_partner",
                                 f"{p.full} has no partner for "
                                 f"{ev} and is open to a random assignment.",
                                 target=f"player:{p.id}"))
            else:
                out.append(Issue("error", "missing_partner",
                                 f"{p.full} entered {ev} with no usable partner "
                                 f"and did not opt into a random partner.",
                                 target=f"player:{p.id}"))

    # One-sided requests (expected on the legacy form; informational).
    edges = {(a, b, ev) for a, b, ev in _resolved_partner_edges(t)}
    # The organizer's pair list settles an event even when the form answers
    # disagree: the request is not something to fix any more.
    paired = {(pid, pr.event) for pr in t.pairs.values()
              for pid in pr.player_ids}
    for a, b, ev in edges:
        if t.players.get(b) and t.players[b].is_stub:
            continue
        if b not in reg_by_player:
            continue
        if (a, ev) in paired or (b, ev) in paired:
            continue
        reciprocated = any(
            (h.resolved_player_id == a and (h.event_hint == ev or not h.event_hint or not ev))
            for h in reg_by_player[b].partner_hints)
        if not reciprocated:
            out.append(Issue("info", "one_sided_partner",
                             f"{t.players[a].full} lists {t.players[b].full} as a "
                             f"partner{f' for {ev}' if ev else ''}, but not vice "
                             f"versa.", target=f"player:{a}"))
    return out


def check_partner_events(t: Tournament) -> list[Issue]:
    """A named partner must be entered in that event -- or have named the player
    back. The form asks for the MD/WD partner and the XD partner separately, so
    naming someone who only signed up for the other discipline is a common
    mistake. Surface it instead of silently seating them in the wrong bracket.
    """
    out, seen = [], set()
    for r in t.registrations:
        p = t.players.get(r.player_id)
        if not p:
            continue
        for h in r.partner_hints:
            if not h.resolved_player_id or h.event_hint not in DOUBLES_EVENTS:
                continue
            partner = t.players.get(h.resolved_player_id)
            if not partner or partner.withdrawn:
                continue
            ev = h.event_hint
            if ev not in p.events:
                continue          # player isn't in this event: nothing to check
            if ev in partner.events:
                continue                      # properly registered
            key = (p.id, partner.id, ev)
            if key in seen:
                continue
            seen.add(key)
            mutual = any(
                hh.resolved_player_id == p.id
                and (hh.event_hint == ev or not hh.event_hint)
                for rr in t.registrations if rr.player_id == partner.id
                for hh in rr.partner_hints)
            theirs = ", ".join(partner.events) or "no events"
            if mutual:
                out.append(Issue(
                    "info", "partner_event_mismatch",
                    f"{partner.full} is not registered for {ev} (entered: {theirs}), "
                    f"but {p.full} named them and they named {p.full} back, so they "
                    f"are paired -- confirm {partner.full} is playing {ev}.",
                    target=f"player:{partner.id}"))
            else:
                out.append(Issue(
                    "warning", "partner_not_entered",
                    f"{p.full} lists {partner.full} as a partner for {ev}, but "
                    f"{partner.full} is registered for {theirs} -- they were not "
                    f"paired. Add {ev} to {partner.full}'s events, or assign "
                    f"{p.full} a different partner.",
                    target=f"player:{p.id}"))
    return out


def check_pair_genders(t: Tournament) -> list[Issue]:
    """A doubles pairing must match its event's gender rule: Men's Doubles = two
    men, Women's Doubles = two women, Mixed = one man + one woman. Checks both
    resolved partner requests (at import) and any materialized pairs (team mode).
    Unknown genders are skipped -- the unknown_gender rule covers those."""
    out, seen = [], set()

    def consider(a, b, ev):
        key = (tuple(sorted((a, b))), ev)
        if key in seen:
            return
        seen.add(key)
        pa, pb = t.players.get(a), t.players.get(b)
        if not pa or not pb or "U" in (pa.gender, pb.gender):
            return
        g = {pa.gender, pb.gender}
        names = f"{pa.full} / {pb.full}"
        if ev == "MD" and g != {"M"}:
            out.append(Issue("warning", "md_gender",
                             f"Men's Doubles pair {names} should be two men "
                             f"(got {pa.gender}/{pb.gender}).", target=f"player:{a}"))
        elif ev == "WD" and g != {"F"}:
            out.append(Issue("warning", "wd_gender",
                             f"Women's Doubles pair {names} should be two women "
                             f"(got {pa.gender}/{pb.gender}).", target=f"player:{a}"))
        elif ev == "XD" and g != {"M", "F"}:
            out.append(Issue("warning", "xd_same_gender",
                             f"Mixed Doubles pair {names} should be one man + one "
                             f"woman (got {pa.gender}/{pb.gender}).",
                             target=f"player:{a}"))

    for a, b, ev in set(_resolved_partner_edges(t)):
        if ev and not partner_confirmed(t, a, b, ev):
            continue          # refused request; check_partner_events explains it
        consider(a, b, ev)
    for pair in t.pairs.values():                      # materialized team pairs
        if len(pair.player_ids) == 2:
            consider(pair.player_ids[0], pair.player_ids[1], pair.event)
    return out


ALL_RULES = [check_skill, check_gender, check_duplicates, check_partners,
             check_partner_events, check_pair_genders]
