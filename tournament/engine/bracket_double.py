"""Double-elimination bracket (any field size).

Winners bracket (WB) runs like single elimination; each WB loser drops into the
losers bracket (LB). The LB alternates *minor* rounds (LB survivors play each
other) and *major* rounds (LB survivors meet the WB losers dropping from the
next WB round), with a cross pairing to avoid immediate rematches. The LB winner
meets the WB winner in the grand final; if the LB winner takes the first grand
final (the WB winner's first loss), a reset (decider) game is played.

Non-power-of-two fields are handled by padding to the next power of two with
"bye" filler entrants: the clean power-of-two structure is built normally, then
any match involving a bye is auto-forfeited (the real side advances), which
cascades correctly through both brackets. Top seeds receive the byes.
"""

from __future__ import annotations

from ..model.entities import Bracket, Division, EntryRef, Match, Round, Seed
from .advancement import record_result
from .bracket_single import round_name
from .seeding import next_power_of_two, place_seeds_in_slots


def generate(division: Division, seeds: list[Seed],
             rng_seed: int | None = None) -> Bracket:
    d = division.id
    br = Bracket(division_id=d, format="double_elim", rng_seed=rng_seed,
                 seeds=list(seeds))
    n = len(seeds)
    if n < 2:
        return br

    # Pad to the next power of two with "bye" fillers so the structure is clean;
    # byes take the lowest seeds, so they land against the top seeds.
    size = next_power_of_two(n)
    padded = list(seeds)
    for i in range(size - n):
        padded.append(Seed(entry=EntryRef("bye", f"{d}-bye-{i}"),
                           seed_no=n + i + 1))
    slots, size = place_seeds_in_slots(padded)
    R = size.bit_length() - 1
    seq = 0

    # --- Winners bracket ----------------------------------------------------
    wb_rounds: list[list[str]] = []
    current = slots
    prev: list[str] = []
    for r in range(R):
        mcount = len(current) // 2
        ids = []
        for j in range(mcount):
            mid = f"{d}-wb-r{r}-m{j}"
            m = Match(id=mid, division_id=d,
                      round_name=f"Winners {round_name(mcount)}",
                      bracket_part="winners", seq=seq); seq += 1
            if r == 0:
                m.side1, m.side2 = current[2 * j], current[2 * j + 1]
            br.matches[mid] = m
            ids.append(mid)
        if r > 0:
            for j, pid in enumerate(prev):
                br.matches[pid].next_win_match = ids[j // 2]
                br.matches[pid].next_win_slot = 1 if j % 2 == 0 else 2
        br.rounds.append(Round(name=f"Winners {round_name(mcount)}",
                              match_ids=ids, bracket_part="winners"))
        wb_rounds.append(ids)
        prev = ids
        current = [None] * mcount
    wb_final = wb_rounds[-1][0]

    # --- Losers bracket -----------------------------------------------------
    lb_final: str | None = None
    lb_round_no = 0

    def add_lb_round(ids: list[str]) -> None:
        br.rounds.append(Round(name=f"Losers Round {lb_round_no}",
                              match_ids=ids, bracket_part="losers"))

    if R >= 2:
        # LB round 1 (minor): pair the WB round-0 losers.
        lb_round_no = 1
        ids = []
        w0 = wb_rounds[0]
        for j in range(len(w0) // 2):
            mid = f"{d}-lb-r{lb_round_no}-m{j}"
            br.matches[mid] = Match(id=mid, division_id=d,
                                    round_name=f"Losers Round {lb_round_no}",
                                    bracket_part="losers", seq=seq); seq += 1
            for k, slot in ((2 * j, 1), (2 * j + 1, 2)):
                br.matches[w0[k]].next_lose_match = mid
                br.matches[w0[k]].next_lose_slot = slot
            ids.append(mid)
        add_lb_round(ids)
        prev_lb = ids

        for wb_r in range(1, R):
            # MAJOR: prev LB winners vs WB round wb_r losers (cross paired).
            lb_round_no += 1
            wl = wb_rounds[wb_r]
            ids = []
            for j in range(len(prev_lb)):
                mid = f"{d}-lb-r{lb_round_no}-m{j}"
                br.matches[mid] = Match(id=mid, division_id=d,
                                        round_name=f"Losers Round {lb_round_no}",
                                        bracket_part="losers", seq=seq); seq += 1
                br.matches[prev_lb[j]].next_win_match = mid
                br.matches[prev_lb[j]].next_win_slot = 1
                drop = wl[len(prev_lb) - 1 - j]        # cross to avoid rematch
                br.matches[drop].next_lose_match = mid
                br.matches[drop].next_lose_slot = 2
                ids.append(mid)
            add_lb_round(ids)
            prev_lb = ids
            # MINOR: pair the major-round winners (if more than one remains).
            if len(prev_lb) > 1:
                lb_round_no += 1
                ids = []
                for j in range(len(prev_lb) // 2):
                    mid = f"{d}-lb-r{lb_round_no}-m{j}"
                    br.matches[mid] = Match(id=mid, division_id=d,
                                            round_name=f"Losers Round {lb_round_no}",
                                            bracket_part="losers", seq=seq); seq += 1
                    for k, slot in ((2 * j, 1), (2 * j + 1, 2)):
                        br.matches[prev_lb[k]].next_win_match = mid
                        br.matches[prev_lb[k]].next_win_slot = slot
                    ids.append(mid)
                add_lb_round(ids)
                prev_lb = ids
        lb_final = prev_lb[0]

    # --- Grand final (+ reset) ---------------------------------------------
    gf1, gf2 = f"{d}-gf-1", f"{d}-gf-2"
    br.matches[gf1] = Match(id=gf1, division_id=d, round_name="Grand Final",
                            bracket_part="grand_final", seq=seq); seq += 1
    br.matches[gf2] = Match(id=gf2, division_id=d, round_name="Grand Final (Reset)",
                            bracket_part="grand_final", seq=seq); seq += 1
    br.rounds.append(Round(name="Grand Final", match_ids=[gf1, gf2],
                          bracket_part="grand_final"))
    # WB winner -> gf slot1.
    br.matches[wb_final].next_win_match = gf1
    br.matches[wb_final].next_win_slot = 1
    if lb_final is not None:
        br.matches[lb_final].next_win_match = gf1
        br.matches[lb_final].next_win_slot = 2
    else:
        # n == 2: the WB final loser is the LB "finalist".
        br.matches[wb_final].next_lose_match = gf1
        br.matches[wb_final].next_lose_slot = 2

    resolve_byes(br)     # auto-forfeit every match that involves a bye filler
    return br


def resolve_byes(bracket: Bracket) -> None:
    """Auto-forfeit any ready match involving a 'bye' filler: the real side
    advances (or a bye advances if both are byes). Repeats until stable, so a
    bye cascades correctly through the winners and losers brackets -- including
    when a real result later feeds a bye's waiting opponent."""
    changed = True
    while changed:
        changed = False
        for m in bracket.matches.values():
            if m.result is not None or m.bracket_part == "grand_final":
                continue
            if m.side1 is None or m.side2 is None:
                continue                        # not ready (a real feeder pending)
            b1, b2 = m.side1.kind == "bye", m.side2.kind == "bye"
            if not (b1 or b2):
                continue                        # real vs real -> play it
            winner = m.side1 if (b2 or not b1) else m.side2   # real side (or side1 if both bye)
            record_result(bracket, m.id, walkover_winner=winner)
            changed = True


def after_result(bracket: Bracket, match_id: str) -> None:
    """Activate the reset game if the LB finalist wins the first grand final,
    and settle any byes that a just-entered result opened up."""
    d = bracket.division_id
    gf1, gf2 = f"{d}-gf-1", f"{d}-gf-2"
    if match_id == gf1:
        m = bracket.matches[gf1]
        if m.result and m.result.winner and m.result.winner == m.side2:
            reset = bracket.matches[gf2]
            reset.side1, reset.side2 = m.side1, m.side2
    resolve_byes(bracket)


def champion(bracket: Bracket):
    d = bracket.division_id
    gf2 = bracket.matches.get(f"{d}-gf-2")
    if gf2 and gf2.result and gf2.result.winner:
        return gf2.result.winner
    gf1 = bracket.matches.get(f"{d}-gf-1")
    if gf1 and gf1.result and gf1.result.winner:
        # WB finalist (slot1) winning means no reset needed.
        if gf1.result.winner == gf1.side1:
            return gf1.result.winner
    return None


def is_inactive_reset(match) -> bool:
    """True for the grand-final reset game before it is needed.

    The reset exists up front but only becomes a real match if the
    loser-bracket finalist wins the first grand final (see ``after_result``).
    An inactive reset has no sides at all, so it needs no court time and should
    not be drawn as a match.
    """
    return (match.bracket_part == "grand_final" and match.result is None
            and match.side1 is None and match.side2 is None
            and match.id.endswith("-gf-2"))
