"""Configurable defaults for the tournament system.

Everything here is a *default*. Real values come from CLI flags, environment
variables, or per-tournament settings stored in the tournament document. Nothing
tournament-specific (durations, court counts, tie-break order) is hardcoded in
the engine modules -- they read from a `Settings` object derived from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

# --- Server -----------------------------------------------------------------
# 8765 chosen because 5000/5001 are used by other local programs.
DEFAULT_PORT = 8765


def resolve_port(cli_port: int | None = None) -> int:
    """CLI flag > BADMINTON_PORT env var > DEFAULT_PORT."""
    if cli_port is not None:
        return cli_port
    env = os.environ.get("BADMINTON_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return DEFAULT_PORT


# --- Domain vocabulary ------------------------------------------------------
EVENT_CODES = ("MS", "WS", "MD", "WD", "XD")
DOUBLES_EVENTS = frozenset({"MD", "WD", "XD"})
SINGLES_EVENTS = frozenset({"MS", "WS"})

EVENT_LABELS = {
    "MS": "Men's Singles",
    "WS": "Women's Singles",
    "MD": "Men's Doubles",
    "WD": "Women's Doubles",
    "XD": "Mixed Doubles",
}

# Gender implied by an event (used to sanity-check, never to overwrite stated data).
EVENT_GENDER = {
    "MS": ("M",),
    "WS": ("F",),
    "MD": ("M",),
    "WD": ("F",),
    "XD": ("M", "F"),  # one of each, ideally
}

FORMAT_NAMES = (
    "single_elim",
    "double_elim",
    "round_robin",
    "group_knockout",
    "swiss",
    "consolation",
    "compass",
)

SKILL_MIN = 1
SKILL_MAX = 9

# --- Match format & scheduling defaults (all overridable) -------------------
# Grounded in the real March event evidence that 20-minute slots were too short.
# NOTE: these durations are practical defaults, not an authoritative standard.


@dataclass(slots=True)
class MatchFormat:
    best_of: int = 3          # best-of-3 games
    points_to: int = 21       # rally scoring to 21
    win_by: int = 2           # must win by 2
    hard_cap: int = 30        # first to 30 wins if it reaches 29-29


@dataclass(slots=True)
class SlotTiming:
    warmup_min: int = 5       # knock-up before the match, inside the slot
    play_min: int = 30        # estimated play time for a best-of-3 to 21
    buffer_min: int = 5       # turnover/reporting buffer after the match

    @property
    def slot_min(self) -> int:
        return self.warmup_min + self.play_min + self.buffer_min


def _pool_timing() -> "SlotTiming":
    # Pool/round-robin matches: a single timed game, short buffer, back-to-back.
    return SlotTiming(warmup_min=0, play_min=10, buffer_min=2)


@dataclass(slots=True)
class Settings:
    """Per-tournament configuration snapshot."""

    court_count: int = 4
    day_start: str = "13:45"          # HH:MM, matches the March event start
    day_end: str = "18:05"            # HH:MM target finish (planner fit window)
    rest_min: int = 10                # minimum rest between a player's matches
    # Courts free of hoops/obstructions -- the only ones knockout (QF/SF/final)
    # matches may use. 1-based court numbers; applies to both the auto-scheduler
    # and the live court board. Pools may use any court.
    center_courts: tuple[int, ...] = (2, 3, 6, 7)
    match_format: MatchFormat = field(default_factory=MatchFormat)
    timing: SlotTiming = field(default_factory=SlotTiming)          # knockout
    # Pool/round-robin stage: shorter, single timed game (see _pool_timing).
    pool_timing: SlotTiming = field(default_factory=_pool_timing)
    pool_single_game: bool = True     # pool matches are one timed game, not Bo3
    # --- team-tournament defaults (only used in team mode; all overridable) ---
    rubber_play: str = "sequential"       # "sequential" | "concurrent"
    dead_rubbers: str = "stop"            # "stop" at clinch | "all" rubbers
    multi_event_cap: int = 2              # max rubbers a (opted-in) player covers per tie
    default_team_preset: str = "sudirman"  # starting rubber template preset
    # Default group-stage tie-break order (BWF-aligned; fully configurable).
    # Deterministic final fallback = seeded position (never a live coin flip).
    tiebreak_order: tuple[str, ...] = (
        "match_wins",
        "head_to_head",
        "game_diff",
        "point_diff",
        "points_for",
        "seed",
    )

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)


DEFAULT_SETTINGS = Settings()

# --- Branding ---------------------------------------------------------------
# Navy sampled directly from web/assets/logo.png (not guessed): rgb(0,46,90).
BYU_NAVY = "#002E5A"
BYU_NAVY_DARK = "#001E3C"
BYU_WHITE = "#FFFFFF"
BYU_ACCENT = "#4A6C94"   # lighter navy for panels/rules, derived from the logo
