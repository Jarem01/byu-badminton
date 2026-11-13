"""Record match results and propagate winners (and losers) through a bracket.

Shared by all knockout formats: single elim uses ``next_win_match`` only;
double elim/consolation also use ``next_lose_match``. Winners are decided by
games won, never by total points.
"""

from __future__ import annotations

from ..config import MatchFormat
from ..model.entities import Bracket, EntryRef, Match, Result


def decide_winner(match: Match, games: list[list[int]],
                  fmt: MatchFormat | None = None) -> tuple[EntryRef, EntryRef]:
    """Return (winner_ref, loser_ref) from per-game scores. Raises on a tie."""
    if match.side1 is None or match.side2 is None:
        raise ValueError("cannot decide a match that is missing a side")
    w1 = sum(1 for g in games if len(g) == 2 and g[0] > g[1])
    w2 = sum(1 for g in games if len(g) == 2 and g[1] > g[0])
    if w1 == w2:
        raise ValueError("games won are tied; no winner can be decided")
    if w1 > w2:
        return match.side1, match.side2
    return match.side2, match.side1


def _place(bracket: Bracket, match_id: str | None, slot: int, ref: EntryRef | None):
    if not match_id or ref is None:
        return
    target = bracket.matches.get(match_id)
    if target is None:
        return
    if slot == 1:
        target.side1 = ref
    else:
        target.side2 = ref


def propagate(bracket: Bracket, match: Match) -> None:
    """Push the decided winner/loser into their downstream slots."""
    if not match.result or match.result.winner is None:
        return
    winner = match.result.winner
    loser = (match.side2 if winner == match.side1 else match.side1)
    _place(bracket, match.next_win_match, match.next_win_slot, winner)
    _place(bracket, match.next_lose_match, match.next_lose_slot, loser)


def _clear_slot(bracket: Bracket, match_id: str | None, slot: int,
                ref: EntryRef | None) -> None:
    """Remove ``ref`` from a downstream slot if present, recursively undoing any
    result that depended on it (used when a prior result is edited)."""
    if not match_id or ref is None:
        return
    tgt = bracket.matches.get(match_id)
    if tgt is None:
        return
    cur = tgt.side1 if slot == 1 else tgt.side2
    if cur is not None and cur == ref:
        if tgt.result is not None:
            unpropagate(bracket, tgt)
            tgt.result = None
        if slot == 1:
            tgt.side1 = None
        else:
            tgt.side2 = None


def unpropagate(bracket: Bracket, match: Match) -> None:
    """Reverse a match's propagation (its winner/loser leaving downstream slots)."""
    if not match.result or match.result.winner is None:
        return
    winner = match.result.winner
    loser = match.side2 if winner == match.side1 else match.side1
    _clear_slot(bracket, match.next_win_match, match.next_win_slot, winner)
    _clear_slot(bracket, match.next_lose_match, match.next_lose_slot, loser)


def record_result(bracket: Bracket, match_id: str,
                  games: list[list[int]] | None = None,
                  walkover_winner: EntryRef | None = None,
                  fmt: MatchFormat | None = None) -> Match:
    match = bracket.matches[match_id]
    old_winner = match.result.winner if match.result else None

    if walkover_winner is not None:
        new_result = Result(games=games or [], winner=walkover_winner, walkover=True)
    else:
        if not games:
            raise ValueError("a non-walkover result needs game scores")
        winner, _loser = decide_winner(match, games, fmt)
        new_result = Result(games=games, winner=winner)

    # If this is an edit that FLIPS the winner, undo the old winner's downstream
    # effect (and anything that cascaded from it) before applying the new one.
    # A pure score correction that keeps the same winner leaves downstream intact.
    if old_winner is not None and old_winner != new_result.winner:
        unpropagate(bracket, match)
    match.result = new_result
    propagate(bracket, match)
    return match


def resolve_byes(bracket: Bracket) -> None:
    """Auto-advance any first-round bye (a match with exactly one side)."""
    if not bracket.rounds:
        return
    for mid in bracket.rounds[0].match_ids:
        m = bracket.matches[mid]
        if m.is_bye() and m.result is None:
            present = m.side1 if m.side1 is not None else m.side2
            record_result(bracket, mid, walkover_winner=present)


def champion(bracket: Bracket) -> EntryRef | None:
    """Winner of the final (last main-bracket round), if decided."""
    mains = [r for r in bracket.rounds if r.bracket_part in ("main", "winners")]
    if not mains:
        return None
    final_ids = mains[-1].match_ids
    if len(final_ids) != 1:
        return None
    res = bracket.matches[final_ids[0]].result
    return res.winner if res else None
