"""Late-arrival handling.

Policy: a late team's lateness eats into *their own* warm-up window; the match
still starts at its scheduled play time and the rest of the day does not shift.
Only if lateness exceeds the whole warm-up does the match risk starting late,
and even then we surface an admin decision rather than auto-cascading delays.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.entities import ScheduleBlock


@dataclass(slots=True)
class LateOutcome:
    usable_warmup_min: int      # warm-up the late team actually gets
    delay_min: int              # minutes the match would start late (0 if none)
    cascades: bool              # True only if a delay is unavoidable
    note: str


def apply_lateness(block: ScheduleBlock, minutes_late: int) -> LateOutcome:
    if minutes_late <= 0:
        return LateOutcome(block.warmup_min, 0, False, "on time")
    if minutes_late <= block.warmup_min:
        return LateOutcome(block.warmup_min - minutes_late, 0, False,
                           f"warm-up cut to {block.warmup_min - minutes_late} min; "
                           f"match starts on schedule")
    # Lateness exceeds warm-up: the team can start with zero warm-up right away,
    # OR the admin may allow a short delay. Default = no cascade (0 warm-up).
    delay = minutes_late - block.warmup_min
    return LateOutcome(0, delay, False,
                       f"{minutes_late} min late exceeds the {block.warmup_min}-min "
                       f"warm-up; start with no warm-up (no cascade) or admin may "
                       f"allow up to {delay} min delay")
