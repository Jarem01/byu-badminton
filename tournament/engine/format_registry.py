"""Map a format name to its bracket generator.

Each generator has signature ``(division, seeds, rng_seed) -> Bracket``. Formats
are registered as they are implemented; unimplemented ones raise a clear error.
"""

from __future__ import annotations

from ..model.entities import Bracket, Division, Seed
from . import bracket_double, bracket_groups, bracket_rr, bracket_single

_GENERATORS = {
    "single_elim": bracket_single.generate,
    "double_elim": bracket_double.generate,
    "round_robin": bracket_rr.generate,
    "group_knockout": bracket_groups.generate,
}


def register(name: str, fn) -> None:
    _GENERATORS[name] = fn


# Register not-yet-implemented formats so they are discoverable and fail clearly.
from . import bracket_stubs  # noqa: E402
bracket_stubs.register_stubs(register)

IMPLEMENTED = ("single_elim", "double_elim", "round_robin", "group_knockout")


def available_formats() -> list[str]:
    return sorted(_GENERATORS)


def generate(format_name: str, division: Division, seeds: list[Seed],
             rng_seed: int | None = None) -> Bracket:
    fn = _GENERATORS.get(format_name)
    if fn is None:
        raise ValueError(
            f"Format {format_name!r} is not implemented yet. "
            f"Available: {', '.join(available_formats())}")
    return fn(division, seeds, rng_seed)
