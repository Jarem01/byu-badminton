"""Time-slot math. A slot = warm-up + play + buffer (all configurable).

Times are tracked as minutes from tournament start (T0 = settings.day_start)
and converted to clock strings only for display.
"""

from __future__ import annotations

from ..config import SlotTiming


def parse_clock(hhmm: str) -> int:
    """'13:45' -> minutes since midnight."""
    h, _, m = hhmm.partition(":")
    return int(h) * 60 + int(m or 0)


def minutes_to_clock(day_start: str, minutes_from_t0: int) -> str:
    total = parse_clock(day_start) + minutes_from_t0
    h, m = divmod(total % (24 * 60), 60)
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ampm}"


def slot_start_min(slot_index: int, timing: SlotTiming) -> int:
    return slot_index * timing.slot_min


def block_times(slot_index: int, timing: SlotTiming) -> tuple[int, int, int]:
    """Return (block_start, play_start, play_end) in minutes from T0."""
    start = slot_start_min(slot_index, timing)
    play_start = start + timing.warmup_min
    return start, play_start, play_start + timing.play_min
