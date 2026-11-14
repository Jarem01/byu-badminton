"""Core tournament data model.

Design principles:
- A doubles entry is a ``Pair`` of two ``Player`` ids -- never a joined string.
- Singles and doubles both flow through ``EntryRef`` so one Match/Bracket/
  advancement code path serves both.
- Brackets are versioned, carry their RNG seed, and can be finalized to guard
  against silent overwrites.
- Results record per-game scores; a winner is derived from games won, never
  from total points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from ..config import Settings

Gender = Literal["M", "F", "U"]  # U = unknown, surfaced for manual fix
EventCode = Literal["MS", "WS", "MD", "WD", "XD"]
FormatName = Literal[
    "single_elim", "double_elim", "round_robin",
    "group_knockout", "swiss", "consolation", "compass",
]
EntryKind = Literal["player", "pair", "slot", "bye", "team"]  # slot = group qualifier; bye = auto-forfeit filler; team = team entry
PairOrigin = Literal["requested", "auto_random", "manual"]
SeedMethod = Literal["manual", "ranking", "random"]
BracketPart = Literal["winners", "losers", "main", "pool", "grand_final", "rubber"]

# --- team-format vocabulary (only used by team-mode tournaments) ---
TournamentMode = Literal["individual", "team"]
TeamType = Literal["mens", "womens", "mixed", "open", "custom"]
Discipline = Literal["singles", "doubles"]
RubberGender = Literal["M", "F", "X", "open"]   # X = mixed (one of each)
PlayMode = Literal["sequential", "concurrent"]
DeadRubberPolicy = Literal["stop", "all"]


@dataclass(slots=True)
class Player:
    id: str
    first: str
    last: str
    email: str = ""
    gender: Gender = "U"
    skill: Optional[int] = None          # 1..9; None => missing/invalid (flagged)
    events: list[EventCode] = field(default_factory=list)
    club: str = ""
    willing_random: bool = True
    weekend_avail: list[str] = field(default_factory=list)
    weekday_avail: list[str] = field(default_factory=list)
    source_row: int = -1                 # trace back to CSV row for audit
    is_stub: bool = False                # created only from a partner mention
    withdrawn: bool = False
    # Self-declared on the form: willing to play more than one rubber in a team
    # tie. Only opted-in players may be doubled-up (capped by settings).
    multi_event_ok: bool = False

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}".strip()


@dataclass(slots=True)
class Pair:
    id: str
    player_ids: list[str]                # exactly two; order not significant
    event: EventCode
    origin: PairOrigin = "requested"

    @property
    def club(self) -> str:
        return ""  # set by grouping when both players share a club


@dataclass(slots=True)
class Team:
    """A team = a bag of intact registered ENTRIES (a doubles pair is one entry,
    a single is one entry), kept as registered. ``entries`` are EntryRefs of
    kind 'pair'/'player'; ``player_ids`` is their flattened union (for rosters /
    no-double-booking). A tie matches two teams' entries by event and rank."""
    id: str
    name: str
    entries: list[EntryRef] = field(default_factory=list)
    player_ids: list[str] = field(default_factory=list)
    club: str = ""
    captain_id: str = ""
    color: str = ""


@dataclass(slots=True)
class Rubber:
    """One sub-match slot within a team tie (e.g. '1st Singles', 'Mixed')."""
    order: int
    discipline: Discipline
    gender: RubberGender
    label: str


@dataclass(slots=True)
class TeamFormat:
    """Config for a team tournament (dual-meet model). A tie's rubbers are the
    two teams' entries matched by event + rank, so the rubber count is dynamic
    per tie (threshold = floor(count/2)+1). ``events`` lists the disciplines in
    play (length 1 => single-event, e.g. team Mixed Doubles). ``rank_by`` +
    points/draw settings drive the team-league ('point system') standings."""
    events: list[str] = field(default_factory=list)   # included events (1 => single-event)
    play_mode: PlayMode = "sequential"
    dead_rubbers: DeadRubberPolicy = "stop"            # stop at clinch vs play all
    rank_by: str = "tie_wins"        # "tie_wins" | "league_points" | "rubbers" | "points"
    win_points: int = 2
    draw_points: int = 1
    loss_points: int = 0
    allow_draw: bool = False         # let a tie end level (even rubber split)
    # How a single team-vs-team tie is contested:
    #   "position" -> rank each team's entries, #1 v #1, #2 v #2, ...
    #   "cross"    -> every A entry plays every B entry in each event (round-robin
    #                 within the tie), tie decided by total matches won.
    tie_format: str = "position"
    # Per-event override of tie_format, e.g. {"MS": "position", "XD": "cross"}.
    event_rules: dict = field(default_factory=dict)
    # "full" = best-of-N to points_to (cap); "quick" = one short timed game.
    match_length: str = "full"
    # Handicap: give the lower-rated side a per-game head start when deciding a
    # rubber (H = min(cap, round(rating gap))). Raw scores are still shown.
    handicap: bool = False
    handicap_cap: int = 8
    rubbers: list[Rubber] = field(default_factory=list)   # legacy/unused in dual-meet


@dataclass(slots=True)
class EntryRef:
    """Unifies singles (a player), doubles (a pair) and teams as one entrant."""
    kind: EntryKind
    ref_id: str

    def key(self) -> str:
        return f"{self.kind}:{self.ref_id}"


@dataclass(slots=True)
class PartnerHint:
    raw_name: str
    event_hint: Optional[EventCode] = None
    resolved_player_id: Optional[str] = None
    confidence: float = 0.0              # difflib ratio, 0..1


@dataclass(slots=True)
class RegistrationEntry:
    """One raw form row after adapter normalization."""
    row_index: int
    player_id: str
    partner_hints: list[PartnerHint] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    code: EventCode
    is_doubles: bool


@dataclass(slots=True)
class Division:
    id: str
    event: EventCode
    label: str
    entry_refs: list[EntryRef] = field(default_factory=list)
    format: FormatName = "single_elim"   # per-division format (draw over entries)
    # Seeding the organizer picked, kept so a rebuild keeps their choice.
    seed_method: SeedMethod = "ranking"
    seed_no: Optional[int] = None
    # Hand-made divisions (custom bracket, team event) survive a table rebuild.
    custom: bool = False
    # Team divisions only: how teams field a tie. Absent (None) => individual.
    team_type: Optional[TeamType] = None
    team_format: Optional[TeamFormat] = None


@dataclass(slots=True)
class Seed:
    entry: EntryRef
    seed_no: int                         # 1 = top seed
    method: SeedMethod = "ranking"


@dataclass(slots=True)
class Result:
    games: list[list[int]] = field(default_factory=list)  # [[21,15],[19,21],[21,17]]
    winner: Optional[EntryRef] = None
    walkover: bool = False

    def games_won(self) -> tuple[int, int]:
        w1 = sum(1 for g in self.games if len(g) == 2 and g[0] > g[1])
        w2 = sum(1 for g in self.games if len(g) == 2 and g[1] > g[0])
        return w1, w2


@dataclass(slots=True)
class Match:
    id: str
    division_id: str
    round_name: str
    bracket_part: BracketPart = "main"
    side1: Optional[EntryRef] = None     # None => bye or not-yet-determined
    side2: Optional[EntryRef] = None
    result: Optional[Result] = None
    next_win_match: Optional[str] = None
    next_lose_match: Optional[str] = None
    next_win_slot: int = 1               # 1 or 2: which slot the winner fills
    next_lose_slot: int = 1
    pool_id: Optional[str] = None
    seq: int = 0                         # display/order index within division
    # Team tie <-> rubber links. A tie (side1/side2 = teams) lists its rubber
    # match ids; each rubber points back at its parent tie.
    sub_match_ids: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None

    def is_bye(self) -> bool:
        return (self.side1 is None) ^ (self.side2 is None)

    def is_ready(self) -> bool:
        return self.side1 is not None and self.side2 is not None


@dataclass(slots=True)
class Round:
    name: str
    match_ids: list[str] = field(default_factory=list)
    bracket_part: BracketPart = "main"


@dataclass(slots=True)
class Pool:
    id: str
    label: str
    entry_refs: list[EntryRef] = field(default_factory=list)
    advance_count: int = 2               # how many advance to knockout


@dataclass(slots=True)
class Bracket:
    division_id: str
    format: FormatName
    matches: dict[str, Match] = field(default_factory=dict)
    rounds: list[Round] = field(default_factory=list)
    pools: list[Pool] = field(default_factory=list)
    seeds: list[Seed] = field(default_factory=list)
    version: int = 1
    rng_seed: Optional[int] = None
    finalized: bool = False
    # group_knockout only: maps each first-round knockout slot to its source
    # pool + rank, e.g. [match_id, slot(1|2), pool_label, rank]. Lets qualifiers
    # fill the draw per-pool as each pool completes.
    ko_plan: list = field(default_factory=list)

    # A round with at most this many matches is a QF (4), SF (2) or final (1):
    # the stage that must be played on unobstructed "center" courts.
    FINALS_ROUND_MAX_MATCHES = 4

    def is_finals_stage(self, match_id: str) -> bool:
        """True if ``match_id`` sits in a QF/SF/final round of this bracket.

        Early knockout rounds (round of 16 and larger) are NOT finals stage, so
        they may use any court -- otherwise a 4-court venue would run its entire
        first round on the two configured center courts.
        """
        for rnd in self.rounds:
            if match_id in rnd.match_ids:
                return len(rnd.match_ids) <= self.FINALS_ROUND_MAX_MATCHES
        return False


@dataclass(slots=True)
class Court:
    id: str
    name: str


@dataclass(slots=True)
class ScheduleBlock:
    match_id: str
    court_id: str
    start_min: int                       # minutes from tournament T0 (day_start)
    warmup_min: int
    play_min: int
    buffer_min: int

    @property
    def end_min(self) -> int:
        return self.start_min + self.warmup_min + self.play_min + self.buffer_min

    @property
    def play_start_min(self) -> int:
        return self.start_min + self.warmup_min


@dataclass(slots=True)
class PairChange:
    """One organizer decision about who plays with whom, kept apart from the
    form answers.

    ``RegistrationEntry.partner_hints`` is what people submitted and is never
    rewritten by the pair editor; a manual pairing, a shuffle, a re-pair or a
    clear is recorded here instead, with a snapshot of the event's pairs after
    the change so the previous arrangement can be restored. The log is also
    written to the append-only audit file (who, when, before, after).
    """
    ts: str
    actor: str
    event: str
    kind: str                            # manual | clear | shuffle | from_forms | undo
    pairs: list[list[str]] = field(default_factory=list)   # player ids, after
    note: str = ""
    # [player_id, event] pairs this change added to someone's entry list (a
    # partner named for an event they had not entered), so undo can take the
    # entry back off.
    added_events: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class MergeChange:
    """One duplicate merge, kept so a wrong survivor can be undone.

    Everything the merge touches is snapshotted before it happens -- both
    players as they were, the registrations that moved, the partner requests
    repointed, the pairs they were in and the division entries that pointed at
    them -- so ``undo_merge`` can put the roster back exactly as it was.
    """
    ts: str
    actor: str
    kept_id: str
    dropped: Player                       # the player that went away, as they were
    kept_before: Player                   # the survivor, as they were
    dropped_regs: list[RegistrationEntry] = field(default_factory=list)
    dropped_reg_at: list[int] = field(default_factory=list)
    kept_reg_before: Optional[RegistrationEntry] = None
    kept_reg_at: int = -1
    pairs: list[Pair] = field(default_factory=list)      # touching either player
    hint_regs: list[RegistrationEntry] = field(default_factory=list)
    divisions: dict[str, list[EntryRef]] = field(default_factory=dict)


@dataclass(slots=True)
class Override:
    """Append-only audit record for every manual data change."""
    ts: str
    actor: str
    target: str                          # "player:<id>" / "match:<id>" / ...
    field_name: str
    old_value: str
    new_value: str
    reason: str = ""


@dataclass(slots=True)
class Tournament:
    """Root aggregate -- the whole persisted document."""
    name: str = "BYU Badminton Tournament"
    date: str = ""                       # ISO date of the event day, if chosen
    schema_version: int = 1
    # "individual" (default, unchanged behavior) or "team".
    mode: TournamentMode = "individual"
    settings: Settings = field(default_factory=Settings)
    players: dict[str, Player] = field(default_factory=dict)
    pairs: dict[str, Pair] = field(default_factory=dict)
    teams: dict[str, Team] = field(default_factory=dict)
    registrations: list[RegistrationEntry] = field(default_factory=list)
    divisions: dict[str, Division] = field(default_factory=dict)
    brackets: dict[str, Bracket] = field(default_factory=dict)  # keyed by division_id
    courts: list[Court] = field(default_factory=list)
    schedule: list[ScheduleBlock] = field(default_factory=list)
    # Live court board: physical court id ("court-1".."court-8") -> match id
    # currently assigned to it. Managed by hand in the Court Manager.
    court_board: dict[str, str] = field(default_factory=dict)
    # Signature of the scheduling-relevant settings when the schedule was last
    # generated; used to warn when settings have since changed.
    schedule_sig: str = ""
    overrides: list[Override] = field(default_factory=list)
    # Organizer pair decisions, newest last (the form answers stay untouched).
    pair_changes: list[PairChange] = field(default_factory=list)
    # Duplicate merges, newest last, each with what it took to undo it.
    merge_changes: list[MergeChange] = field(default_factory=list)

    # --- convenience lookups (not serialized behavior, just helpers) ---
    def entry_label(self, ref: EntryRef) -> str:
        """Human-readable name for a player, pair, qualifier-slot, or bye entry."""
        if ref.kind == "bye":
            return "Bye"
        if ref.kind == "team":
            team = self.teams.get(ref.ref_id)
            return team.name if team else ref.ref_id
        if ref.kind == "slot":
            # ref_id is "<label>#<rank>", e.g. "A#1"; or "W#<n>" for a wildcard
            # (best-remaining) qualifier that fills the draw to a power of two.
            label, _, rank = ref.ref_id.partition("#")
            if label == "W":
                return f"Wildcard {rank}"
            if rank == "1":
                return f"Winner Pool {label}"
            if rank == "2":
                return f"Runner-up Pool {label}"
            return f"Pool {label} #{rank}"
        if ref.kind == "player":
            p = self.players.get(ref.ref_id)
            return p.full if p else ref.ref_id
        pair = self.pairs.get(ref.ref_id)
        if not pair:
            return ref.ref_id
        names = [self.players[pid].full for pid in pair.player_ids
                 if pid in self.players]
        return " / ".join(names) if names else ref.ref_id
