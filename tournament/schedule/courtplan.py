"""The center-court rule, defined once.

QF/SF/final ("finals stage") knockout matches should be played on unobstructed
center courts. Two details belong to that rule, and both live here so the
auto-scheduler and the live court board can never disagree about them:

* ``is_center_court_match`` -- which matches need a center court (a knockout
  match in a round of <= 4 matches: QF, SF or final). Pool matches, team
  rubbers and early knockout rounds (round of 16 and larger) do not.
* ``center_court_numbers`` -- which of the configured center courts are actually
  usable, given the courts this venue has.

If fewer than two center courts exist, reserving them would starve the venue
(everything else would collapse onto one court), so the rule is dropped
entirely and every court stays usable. That fallback is implemented here once
rather than duplicated by each caller.
"""

from __future__ import annotations

from typing import Iterable

MIN_CENTER_COURTS = 2


def is_center_court_match(bracket, match) -> bool:
    """True if ``match`` must be played on a center court.

    ``bracket`` is the match's ``Bracket`` (it knows which round it is in).
    """
    if match.bracket_part in ("pool", "rubber"):
        return False
    return bracket.is_finals_stage(match.id)


def center_court_numbers(settings, court_numbers: Iterable[int]) -> list[int]:
    """Center court numbers that exist at this venue and should be enforced.

    Empty means "don't enforce": fewer than ``MIN_CENTER_COURTS`` usable center
    courts, so any court may host a knockout match.
    """
    configured = set(settings.center_courts or ())
    usable = sorted(n for n in court_numbers if n in configured)
    return usable if len(usable) >= MIN_CENTER_COURTS else []
