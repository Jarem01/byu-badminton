"""Turn a validated roster into divisions of entrants (players / pairs).

For singles events each player becomes an entry. For doubles events pairs are
formed from explicit partner requests first, then remaining willing players are
auto-paired (mixed doubles pairs one man with one woman). Auto-pairing is
seedable so the result is reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..config import DOUBLES_EVENTS, EVENT_LABELS, EVENT_CODES, SINGLES_EVENTS
from ..model.entities import Division, EntryRef, Pair, Tournament
from ..model.ids import IdFactory


@dataclass(slots=True)
class GroupingResult:
    divisions: dict[str, Division] = field(default_factory=dict)
    auto_paired: list[str] = field(default_factory=list)   # human-readable notes
    unpaired: list[str] = field(default_factory=list)      # player ids left over
    unpaired_labels: list[str] = field(default_factory=list)  # "Name (EV)"


def _id_factory(t: Tournament) -> IdFactory:
    f = IdFactory()
    for pid in t.players:
        f.reserve(pid)
    for pid in t.pairs:
        f.reserve(pid)
    return f


def _active_players_in(t: Tournament, event: str) -> list[str]:
    return [p.id for p in t.players.values()
            if event in p.events and not p.withdrawn]


def _partner_for_event(t: Tournament, player_id: str, event: str) -> str | None:
    for r in t.registrations:
        if r.player_id != player_id:
            continue
        for h in r.partner_hints:
            if h.resolved_player_id and (h.event_hint == event or not h.event_hint):
                return h.resolved_player_id
    return None


def _requests(t: Tournament, player_id: str, partner_id: str, event: str) -> bool:
    """True if ``player_id`` named ``partner_id`` as their partner for ``event``."""
    for r in t.registrations:
        if r.player_id != player_id:
            continue
        for h in r.partner_hints:
            if (h.resolved_player_id == partner_id
                    and (h.event_hint == event or not h.event_hint)):
                return True
    return False


def partner_confirmed(t: Tournament, pid: str, partner: str, event: str,
                      entered: set[str] | None = None) -> bool:
    """Whether a requested partner may be paired for ``event``.

    Normally the partner must be entered in the event. The exception is a mutual
    request: a partner who named this player back (e.g. someone who forgot to
    tick XD but wrote the partner's name in the XD column). A one-sided request
    to an unregistered player is refused, so nobody is silently dragged into an
    event they never signed up for.

    Shared with the validation rules so "this request will not be honoured" is
    reported consistently everywhere.
    """
    if entered is None:
        entered = set(_active_players_in(t, event))
    return partner in entered or _requests(t, partner, pid, event)


def _shared_club(t: Tournament, a: str, b: str) -> str:
    ca, cb = t.players[a].club, t.players[b].club
    return ca if ca and ca == cb else ""


def form_pairs_for_event(t: Tournament, event: str, ids: IdFactory,
                         rng: random.Random, result: GroupingResult,
                         auto_pair: bool = True) -> list[EntryRef]:
    entered = _active_players_in(t, event)
    entered_set = set(entered)
    paired: set[str] = set()
    entries: list[EntryRef] = []

    # Pairs already on the roster (hand-made in the pairs editor) are kept: only
    # the players still on their own get paired below.
    for pr in sorted(t.pairs.values(), key=lambda x: x.id):
        if (pr.event == event and len(pr.player_ids) == 2
                and all(p in entered_set and p not in paired
                        for p in pr.player_ids)):
            entries.append(EntryRef("pair", pr.id))
            paired.update(pr.player_ids)

    def make_pair(a: str, b: str, origin: str) -> None:
        pid = ids.make("pair", t.players[a].last or a, t.players[b].last or b)
        t.pairs[pid] = Pair(id=pid, player_ids=[a, b], event=event, origin=origin)
        entries.append(EntryRef("pair", pid))
        paired.add(a)
        paired.add(b)

    # 1. Explicit partner requests.
    for pid in entered if auto_pair else ():
        if pid in paired:
            continue
        partner = _partner_for_event(t, pid, event)
        if (partner and partner != pid and partner not in paired
                and partner_confirmed(t, pid, partner, event, entered_set)):
            make_pair(pid, partner, "requested")

    # 2. Auto-pair remaining willing players.
    leftover = ([p for p in entered if p not in paired and t.players[p].willing_random]
                if auto_pair else [])
    if event == "XD":
        men = [p for p in leftover if t.players[p].gender == "M"]
        women = [p for p in leftover if t.players[p].gender == "F"]
        rng.shuffle(men)
        rng.shuffle(women)
        for a, b in zip(men, women):
            make_pair(a, b, "auto_random")
            result.auto_paired.append(
                f"{event}: auto-paired {t.players[a].full} + {t.players[b].full}")
    else:
        rng.shuffle(leftover)
        for i in range(0, len(leftover) - 1, 2):
            a, b = leftover[i], leftover[i + 1]
            make_pair(a, b, "auto_random")
            result.auto_paired.append(
                f"{event}: auto-paired {t.players[a].full} + {t.players[b].full}")

    # 3. Anyone still unpaired (odd one out, not willing, or no XD counterpart).
    for pid in entered:
        if pid not in paired:
            result.unpaired.append(pid)
            result.unpaired_labels.append(f"{t.players[pid].full} ({event})")

    return entries


def ensure_pairs(t: Tournament, events: list[str], rng_seed: int = 0) -> "GroupingResult":
    """Materialize doubles pairs for ``events`` from partner hints + auto-pairing,
    ONCE per event (idempotent -- skips an event that already has pairs). Team
    mode needs pairs even though it doesn't run build_divisions; running this in
    both flows is safe because it never double-creates."""
    from ..config import DOUBLES_EVENTS
    ids = _id_factory(t)
    rng = random.Random(rng_seed)
    result = GroupingResult()
    for ev in events or []:
        if ev in DOUBLES_EVENTS and not any(p.event == ev for p in t.pairs.values()):
            form_pairs_for_event(t, ev, ids, rng, result)
    return result


def build_divisions(t: Tournament, events: list[str] | None = None,
                    rng_seed: int | None = None,
                    auto_pair: bool = True) -> GroupingResult:
    """Create one division per event and populate its entries.

    Mutates ``t.pairs`` (adds formed pairs) and ``t.divisions``.
    """
    events = events or list(EVENT_CODES)
    ids = _id_factory(t)
    rng = random.Random(rng_seed)
    result = GroupingResult()

    for event in events:
        if event in SINGLES_EVENTS:
            entries = [EntryRef("player", p.id) for p in t.players.values()
                       if event in p.events and not p.withdrawn]
        elif event in DOUBLES_EVENTS:
            entries = form_pairs_for_event(t, event, ids, rng, result,
                                           auto_pair=auto_pair)
        else:
            continue
        if not entries:
            continue
        div_id = ids.make("div", event)
        div = Division(id=div_id, event=event,
                       label=EVENT_LABELS.get(event, event), entry_refs=entries)
        t.divisions[div_id] = div
        result.divisions[div_id] = div

    return result
