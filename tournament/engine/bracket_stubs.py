"""Placeholder generators for formats not yet implemented.

Registered so the format is a first-class, discoverable option that fails with a
clear, honest message instead of a mysterious error. Swiss is dynamic (pairings
depend on prior results) and does not fit the generate-whole-bracket-upfront
model without a round-by-round pairing loop; compass and consolation are planned
extensions of the knockout engine. See docs/RESEARCH.md for the intended design.
"""

from __future__ import annotations

from ..model.entities import Bracket, Division, Seed

_NOTE = {
    "swiss": "Swiss pairs each round from standings after the previous round; "
             "it needs a round-by-round pairing loop (planned). Use round_robin "
             "or group_knockout for now.",
    "consolation": "Consolation (losers get extra matches) is a planned extension "
                   "of the knockout engine. Use double_elim for a full second-chance "
                   "bracket in the meantime.",
    "compass": "Compass draw (directional consolation brackets) is planned. Use "
               "single_elim or double_elim for now.",
}


def _unimplemented(name: str):
    def gen(division: Division, seeds: list[Seed],
            rng_seed: int | None = None) -> Bracket:
        raise NotImplementedError(f"{name}: {_NOTE.get(name, 'not implemented yet')}")
    return gen


def register_stubs(register) -> None:
    for name in ("swiss", "consolation", "compass"):
        register(name, _unimplemented(name))
