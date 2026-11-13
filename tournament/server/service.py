"""Application service: the single place that mutates and persists state.

Handlers stay thin -- each API endpoint calls one method here. All mutations
take a lock and save atomically. Import is preview-then-commit so nothing is
written until a human approves it (matches the review-before-action rule).
"""

from __future__ import annotations

import threading

from ..config import DEFAULT_SETTINGS
from ..engine import (
    bracket_double, bracket_groups, format_registry, team_build, tie,
)
from ..engine.advancement import champion, record_result, unpropagate
from ..engine.grouping import build_divisions
from ..engine.seeding import seed_entries
from ..engine.standings import all_standings
from ..schedule.best_date import availability_report
from ..schedule.courtplan import center_court_numbers, is_center_court_match
from ..schedule.scheduler import generate_schedule, match_player_ids, player_conflicts
from ..schedule.timeslots import minutes_to_clock
from ..ingest.importer import build_tournament
from ..ingest.source_csv import read_rows, read_rows_from_text
from ..ingest.source_gsheet import fetch_rows
from ..config import Settings
from ..model.entities import Bracket, EntryRef, Tournament
from ..schedule.timeslots import parse_clock
from ..store.repository import Repository
from ..validate.dashboard import validate
from ..validate.overrides import apply_override


class Conflict(Exception):
    """Raised when an action would overwrite finalized/protected state."""


# Entry kinds that represent a real, decided side. "slot" (a group qualifier /
# wildcard placeholder) and "bye" are not playable: scoring a match between them
# would record a fake result (e.g. a champion named "Winner Pool A").
PLAYABLE_SIDE_KINDS = ("player", "pair", "team")


def _playable_side(ref) -> bool:
    return ref is not None and ref.kind in PLAYABLE_SIDE_KINDS


class TournamentService:
    def __init__(self, repo: Repository, actor: str = "admin") -> None:
        self.repo = repo
        self.actor = actor
        self.t: Tournament = repo.load()
        self._preview: object | None = None
        self._lock = threading.RLock()

    # --- helpers ------------------------------------------------------------
    def _save(self, backup: bool = False) -> None:
        self.repo.save(self.t, backup=backup)

    def _entry_view(self, ref: EntryRef | None):
        if ref is None:
            return None
        ev = {"key": ref.key(), "kind": ref.kind,
              "label": self.t.entry_label(ref)}
        if ref.kind == "team":
            team = self.t.teams.get(ref.ref_id)
            if team and team.color:
                ev["color"] = team.color
        return ev

    # --- import (preview then commit) --------------------------------------
    def import_preview(self, source: str, ref: str, schema: str = "auto") -> dict:
        with self._lock:
            if source == "url":
                headers, rows = fetch_rows(ref)
            elif source == "text":
                headers, rows = read_rows_from_text(ref)
            else:
                headers, rows = read_rows(ref)
            result = build_tournament(headers, rows, schema=schema,
                                      name=self.t.name or "BYU Badminton Tournament")
            self._preview = result
            report = validate(result.tournament, extra=result.issues)
            return {
                "adapter": result.adapter,
                "stats": result.stats,
                "validation": report.as_dict(),
                "players": [
                    {"id": p.id, "name": p.full, "gender": p.gender,
                     "skill": p.skill, "events": p.events, "stub": p.is_stub}
                    for p in sorted(result.tournament.players.values(),
                                    key=lambda x: x.full)],
            }

    # --- clear (downstream-only resets) ------------------------------------
    def clear(self, stage: str) -> dict:
        """Clear the progress of one stage and everything downstream of it,
        never touching upstream stages. Chain: import -> divisions/pairs ->
        brackets(+seeds) -> results -> schedule."""
        with self._lock:
            if stage == "import":
                self.t.players.clear()
                self.t.registrations.clear()
                self.t.divisions.clear()
                self.t.pairs.clear()
                self.t.teams.clear()          # team rosters are downstream of import
                self.t.brackets.clear()
                self.t.schedule = []
                self.t.court_board.clear()    # court refs now point at nothing
                self._preview = None
            elif stage == "divisions":
                self.t.divisions.clear()
                self.t.pairs.clear()
                self.t.teams.clear()          # teams are built with divisions
                self.t.brackets.clear()
                self.t.schedule = []
                self.t.court_board.clear()
            elif stage == "schedule":
                self.t.schedule = []
            elif stage == "scores":
                # Rebuild every bracket from its saved seeds/format: identical
                # structure and match ids, but all results wiped and knockout
                # placeholders/byes restored. Un-finalizes (it's reopened).
                for div_id, br in list(self.t.brackets.items()):
                    div = self.t.divisions[div_id]
                    if br.format == "group_knockout":
                        ng = len(br.pools) or 2
                        main = next((r for r in br.rounds
                                     if r.bracket_part == "main"), None)
                        draw = len(main.match_ids) * 2 if main else None
                        new = bracket_groups.generate(div, br.seeds, br.rng_seed, ng, draw)
                    else:
                        new = format_registry.generate(br.format, div, br.seeds,
                                                        br.rng_seed)
                    new.version = br.version
                    self.t.brackets[div_id] = new
                    if div.team_format:       # rebuild the tie rubbers too
                        tie.fill_ties_from_draw(self.t, new)
            else:
                raise ValueError(f"unknown clear stage {stage!r}")
            self._save(backup=True)
            return {"ok": True, "stage": stage}

    def import_commit(self) -> dict:
        with self._lock:
            if self._preview is None:
                raise ValueError("no import to commit; preview first")
            tournament = self._preview.tournament  # type: ignore[attr-defined]
            # An import replaces the roster (and everything drawn from it), but
            # never the organizer's configuration: keep the saved settings, mode
            # and event date instead of silently reverting to the defaults.
            tournament.settings = self.t.settings
            tournament.mode = self.t.mode
            tournament.date = self.t.date
            self.t = tournament
            self._preview = None
            self._save(backup=True)
            return {"players": len(self.t.players),
                    "registrations": len(self.t.registrations)}

    # --- settings (editable, persisted) ------------------------------------
    def get_settings(self) -> dict:
        s = self.t.settings
        return {
            "court_count": s.court_count, "day_start": s.day_start,
            "day_end": s.day_end, "rest_min": s.rest_min,
            "warmup_min": s.timing.warmup_min, "play_min": s.timing.play_min,
            "buffer_min": s.timing.buffer_min, "slot_min": s.timing.slot_min,
            "pool_warmup_min": s.pool_timing.warmup_min,
            "pool_play_min": s.pool_timing.play_min,
            "pool_buffer_min": s.pool_timing.buffer_min,
            "pool_slot_min": s.pool_timing.slot_min,
            "pool_single_game": s.pool_single_game,
            "best_of": s.match_format.best_of, "points_to": s.match_format.points_to,
            "win_by": s.match_format.win_by, "hard_cap": s.match_format.hard_cap,
            "tiebreak_order": list(s.tiebreak_order),
        }

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            s = self.t.settings
            for k in ("court_count", "rest_min"):
                if k in patch:
                    setattr(s, k, max(1, int(patch[k])))
            if "day_start" in patch and patch["day_start"]:
                s.day_start = str(patch["day_start"])
            if "day_end" in patch and patch["day_end"]:
                s.day_end = str(patch["day_end"])
            for k in ("warmup_min", "play_min", "buffer_min"):
                if k in patch:
                    setattr(s.timing, k, max(0, int(patch[k])))
            for k, attr in (("pool_warmup_min", "warmup_min"),
                            ("pool_play_min", "play_min"),
                            ("pool_buffer_min", "buffer_min")):
                if k in patch:
                    setattr(s.pool_timing, attr, max(0, int(patch[k])))
            if "pool_single_game" in patch:
                s.pool_single_game = bool(patch["pool_single_game"])
            for k in ("best_of", "points_to", "win_by", "hard_cap"):
                if k in patch:
                    setattr(s.match_format, k, max(1, int(patch[k])))
            if patch.get("tiebreak_order"):
                s.tiebreak_order = tuple(patch["tiebreak_order"])
            self._save()
            return self.get_settings()

    # --- custom / manual division ------------------------------------------
    def create_custom_division(self, label: str, kind: str, entries: list[str],
                               event: str = "MS", fmt: str = "single_elim") -> dict:
        """Build a division from manually typed entrants (no import needed).

        kind="player": each line is a name (optionally "Name:skill").
        kind="pair":   each line is "Name A / Name B" (each optionally :skill).
        """
        from ..engine.grouping import _id_factory
        from ..model.entities import Division, EntryRef, Pair, Player

        with self._lock:
            ids = _id_factory(self.t)

            def make_player(token: str) -> str:
                token = token.strip()
                skill = None
                if ":" in token:
                    token, _, sk = token.rpartition(":")
                    skill = int(sk) if sk.strip().isdigit() else None
                    token = token.strip()
                parts = token.split()
                first = parts[0] if parts else "Player"
                last = " ".join(parts[1:])
                pid = ids.make("player", first, last or first)
                self.t.players[pid] = Player(id=pid, first=first, last=last,
                                             skill=skill, events=[event])
                return pid

            refs: list[EntryRef] = []
            for line in entries:
                line = line.strip()
                if not line:
                    continue
                if kind == "pair":
                    parts = [p for p in line.replace("/", ",").split(",") if p.strip()]
                    if len(parts) < 2:
                        continue
                    a, b = make_player(parts[0]), make_player(parts[1])
                    pid = ids.make("pair", self.t.players[a].last or a,
                                   self.t.players[b].last or b)
                    self.t.pairs[pid] = Pair(id=pid, player_ids=[a, b], event=event,
                                             origin="manual")
                    refs.append(EntryRef("pair", pid))
                else:
                    refs.append(EntryRef("player", make_player(line)))

            if len(refs) < 2:
                raise ValueError("need at least 2 entrants for a bracket")
            div_id = ids.make("div", event, label)
            self.t.divisions[div_id] = Division(id=div_id, event=event, label=label,
                                                entry_refs=refs, format=fmt)
            self._save(backup=True)
            return {"id": div_id, "label": label, "entries": len(refs), "format": fmt}

    # --- team tournaments ---------------------------------------------------
    def set_mode(self, mode: str) -> dict:
        with self._lock:
            if mode not in ("individual", "team"):
                raise ValueError("mode must be 'individual' or 'team'")
            self.t.mode = mode
            self._save()
            return {"mode": self.t.mode}

    def _team_format_from_spec(self, spec, team_type="open"):
        from ..model.entities import TeamFormat
        spec = spec or {}
        events = spec.get("events") or team_build.TYPE_EVENTS.get(
            team_type, list(team_build.ALL_EVENTS))
        return TeamFormat(
            events=list(events),
            play_mode=spec.get("play_mode", self.t.settings.rubber_play),
            dead_rubbers=spec.get("dead_rubbers", self.t.settings.dead_rubbers),
            rank_by=spec.get("rank_by", "tie_wins"),
            win_points=int(spec.get("win_points", 2)),
            draw_points=int(spec.get("draw_points", 1)),
            loss_points=int(spec.get("loss_points", 0)),
            allow_draw=bool(spec.get("allow_draw", False)),
            tie_format=spec.get("tie_format", "position"),
            event_rules=dict(spec.get("event_rules", {})),
            match_length=spec.get("match_length", "full"),
            handicap=bool(spec.get("handicap", False)),
            handicap_cap=int(spec.get("handicap_cap", 8)))

    def _build_teams(self, opts: dict):
        from ..engine.grouping import ensure_pairs
        team_type = opts.get("team_type", "open")
        fmt = self._team_format_from_spec(opts.get("template"), team_type)
        # Team mode skips build_divisions, so materialize doubles pairs here
        # (idempotent) -- otherwise a doubles team event finds no entries.
        ensure_pairs(self.t, fmt.events, opts.get("rng_seed", 0))
        teams, report = team_build.build_teams(
            self.t, opts.get("method", "balanced"),
            num_teams=opts.get("num_teams"),
            players_per_team=opts.get("players_per_team"),
            events=fmt.events, team_type=team_type,
            rng_seed=opts.get("rng_seed", 0), manual=opts.get("manual"))
        asked = opts.get("num_teams")
        # by_club and manual rosters decide the team count themselves, so asking
        # for a number there is not a shortfall worth warning about.
        if asked and opts.get("method", "balanced") not in ("by_club", "manual") \
                and len(teams) < int(asked):
            # A pair can't be split across two teams, so a roster whose partner
            # links join everyone can only make one team. Say so instead of
            # quietly returning fewer teams than were asked for.
            report["warnings"] = list(report.get("warnings") or []) + [
                f"asked for {asked} teams but only {len(teams)} can be formed: "
                f"the partner links join all players into {len(teams)} group(s), "
                f"and a pair can't be split across teams. Pick fewer teams, a "
                f"single event, or clear some partner links first."]
        return teams, report, fmt

    def _entry_group_view(self, tm) -> list[dict]:
        """A team's entries grouped by event, with gender + avg skill."""
        from ..engine.seeding import entry_strength
        from ..engine.team_build import entry_event, entry_players
        groups: dict[str, list[dict]] = {}
        for e in tm.entries:
            ev = entry_event(self.t, e)
            pl = entry_players(self.t, e)
            genders = "".join(self.t.players[p].gender for p in pl if p in self.t.players)
            groups.setdefault(ev, []).append({
                "label": self.t.entry_label(e),
                "gender": genders,
                "skill": round(entry_strength(self.t, e), 1)})
        return [{"event": ev, "entries": groups[ev]} for ev in sorted(groups)]

    def team_preview(self, opts: dict) -> dict:
        """Build teams WITHOUT committing, for the live roster preview."""
        teams, report, fmt = self._build_teams(opts)
        return {
            "teams": [{"id": tm.id, "name": tm.name, "size": len(tm.entries),
                       "color": tm.color, "by_event": self._entry_group_view(tm)}
                      for tm in teams],
            "report": report, "events": fmt.events,
        }

    def commit_teams(self, opts: dict) -> dict:
        """Persist teams + a team division (entry_refs = team refs)."""
        from ..engine.grouping import _id_factory
        from ..model.entities import Division, EntryRef
        with self._lock:
            teams, report, fmt = self._build_teams(opts)
            ids = _id_factory(self.t)
            refs = []
            self.t.mode = "team"
            for tm in teams:
                tid = ids.make("team", tm.name)
                tm.id = tid
                self.t.teams[tid] = tm
                refs.append(EntryRef("team", tid))
            if len(refs) < 2:
                raise ValueError(
                    f"only {len(refs)} team could be formed for events "
                    f"{', '.join(fmt.events)} — there aren't enough entries. "
                    "Check the selected event(s) and that registrations imported "
                    "(doubles need a partner).")
            label = opts.get("label", "Team Event")
            event = fmt.events[0] if len(fmt.events) == 1 else "MD"
            div_id = ids.make("div", event, label)
            self.t.divisions[div_id] = Division(
                id=div_id, event=event, label=label, entry_refs=refs,
                format=opts.get("format", "single_elim"),
                team_type=opts.get("team_type", "open"), team_format=fmt)
            self._save(backup=True)
            return {"id": div_id, "label": label, "teams": len(refs), "report": report}

    def set_team_format(self, division_id: str, spec) -> dict:
        """Update a team division's tie/league settings. Only rebuilds rubbers
        (which wipes their scores) when the EVENTS change; a scoring-only change
        (ranking / points / draws / play mode) preserves results and just
        re-decides the ties."""
        with self._lock:
            div = self.t.divisions[division_id]
            old = div.team_format
            old_shape = ((list(old.events), old.tie_format, dict(old.event_rules))
                         if old else None)
            div.team_format = self._team_format_from_spec(spec, div.team_type or "open")
            new = div.team_format
            new_shape = (list(new.events), new.tie_format, dict(new.event_rules))
            br = self.t.brackets.get(division_id)
            if br is not None:
                if new_shape != old_shape:
                    # Events/tie-format/per-event rules changed -> the rubber SET
                    # changes; rebuild them (wipes rubber scores).
                    for m in list(br.matches.values()):
                        if m.bracket_part == "rubber":
                            del br.matches[m.id]
                        else:
                            if m.result is not None:
                                unpropagate(br, m)
                                m.result = None
                            m.sub_match_ids = []
                    tie.fill_ties_from_draw(self.t, br)
                else:
                    # Scoring-only change: keep rubber results, just re-decide.
                    for m in list(br.matches.values()):
                        if tie.is_tie(m) and m.sub_match_ids:
                            tie.decide_tie(self.t, br, m)
                self._save(backup=True)
            else:
                self._save()
            return {"ok": True, "events": div.team_format.events}

    # --- validation & overrides --------------------------------------------
    def validation(self) -> dict:
        return validate(self._active()).as_dict()

    def override(self, target: str, field_name: str, value: str,
                 reason: str = "") -> dict:
        with self._lock:
            # Edit the pending preview if one is open, so a fix made before
            # committing is validated correctly AND survives the commit.
            ov = apply_override(self._active(), self.actor, target, field_name,
                                value, reason)
            self.repo.append_audit(ov)
            if self._preview is None:
                self._save()
            return {"ok": True, "audited": ov.ts}

    def _active(self):
        """The tournament to read/edit right now: the pending import preview if
        one is open (so inline fixes apply there and survive commit), else the
        committed tournament."""
        return self._preview.tournament if self._preview else self.t

    # --- reads --------------------------------------------------------------
    def players(self) -> list[dict]:
        return [{"id": p.id, "name": p.full, "gender": p.gender, "skill": p.skill,
                 "events": p.events, "club": p.club, "stub": p.is_stub,
                 "withdrawn": p.withdrawn, "willing_random": p.willing_random}
                for p in sorted(self._active().players.values(), key=lambda x: x.full)]

    def divisions(self) -> list[dict]:
        out = []
        for d in self.t.divisions.values():
            br = self.t.brackets.get(d.id)
            out.append({"id": d.id, "event": d.event, "label": d.label,
                        "format": d.format, "entries": len(d.entry_refs),
                        "has_bracket": br is not None,
                        "finalized": br.finalized if br else False})
        return sorted(out, key=lambda x: x["event"])

    # --- grouping / seeding / brackets -------------------------------------
    def build_divisions(self, rng_seed: int | None = None) -> dict:
        with self._lock:
            # Rebuild from scratch, but never wipe a finalized bracket silently.
            finalized = [d for d in self.t.divisions
                         if self.t.brackets.get(d) and self.t.brackets[d].finalized]
            if finalized:
                raise Conflict(f"{len(finalized)} finalized bracket(s) exist; "
                               "un-finalize before rebuilding divisions.")
            self.t.divisions.clear()
            self.t.pairs.clear()
            self.t.brackets.clear()
            res = build_divisions(self.t, rng_seed=rng_seed)
            self._save(backup=True)
            return {"divisions": self.divisions(),
                    "auto_paired": res.auto_paired,
                    "unpaired": res.unpaired_labels}

    def set_format(self, division_id: str, fmt: str) -> dict:
        with self._lock:
            div = self.t.divisions[division_id]
            div.format = fmt
            self._save()
            return {"ok": True, "format": fmt}

    def seed_preview(self, division_id: str, method: str = "ranking",
                     rng_seed: int | None = None,
                     manual_order: list[str] | None = None) -> dict:
        div = self.t.divisions[division_id]
        seeds = seed_entries(self.t, div, method, rng_seed, manual_order)
        return {"seeds": [{"seed_no": s.seed_no, "key": s.entry.key(),
                           "label": self.t.entry_label(s.entry)} for s in seeds]}

    def generate_bracket(self, division_id: str, fmt: str | None = None,
                         method: str = "ranking", rng_seed: int | None = None,
                         manual_order: list[str] | None = None,
                         force: bool = False, num_groups: int | None = None,
                         main_draw: int | None = None) -> dict:
        with self._lock:
            div = self.t.divisions[division_id]
            existing = self.t.brackets.get(division_id)
            if existing and existing.finalized and not force:
                raise Conflict("bracket is finalized; pass force=true to replace it")
            fmt = fmt or div.format
            div.format = fmt
            seeds = seed_entries(self.t, div, method, rng_seed, manual_order)
            if fmt == "group_knockout":
                br = bracket_groups.generate(div, seeds, rng_seed, num_groups,
                                             main_draw)
            else:
                br = format_registry.generate(fmt, div, seeds, rng_seed)
            if existing:
                br.version = existing.version + 1
            self.t.brackets[division_id] = br
            if div.team_format:            # team draw: build + fill ready ties
                tie.fill_ties_from_draw(self.t, br, self.t.settings.multi_event_cap)
            self._save(backup=True)
            return self.bracket_view(division_id)

    def finalize(self, division_id: str) -> dict:
        with self._lock:
            self.t.brackets[division_id].finalized = True
            self._save()
            return {"ok": True, "finalized": True}

    def unfinalize(self, division_id: str) -> dict:
        with self._lock:
            self.t.brackets[division_id].finalized = False
            self._save()
            return {"ok": True, "finalized": False}

    def record_result(self, division_id: str, match_id: str,
                      games: list[list[int]]) -> dict:
        with self._lock:
            br = self.t.brackets[division_id]
            div = self.t.divisions[division_id]
            m = br.matches[match_id]
            if not _playable_side(m.side1) or not _playable_side(m.side2):
                raise ValueError(
                    "that match isn't ready to play: one or both sides are still "
                    "undecided (pool qualifiers or a pending feeder match)")
            if div.team_format and m.parent_id:
                # A team rubber: decide with any handicap, then re-decide its tie
                # and advance the draw.
                tie.record_rubber(self.t, br, m, games, div.team_format)
                tie.decide_tie(self.t, br, br.matches[m.parent_id])
                tie.fill_ties_from_draw(self.t, br, self.t.settings.multi_event_cap)
            else:
                record_result(br, match_id, games)
                if br.format == "group_knockout":
                    bracket_groups.fill_knockout_from_pools(self.t, br)
                elif br.format == "double_elim":
                    bracket_double.after_result(br, match_id)
            self._save()
            return self.bracket_view(division_id)

    # --- live court board (manual drag-and-drop, global across divisions) ----
    CENTER_COURTS = {2, 3, 6, 7}   # default; real value comes from settings

    def _court_count(self) -> int:
        """How many courts this tournament actually has."""
        return max(1, int(self.t.settings.court_count or 1))

    @staticmethod
    def _court_num(court_id: str) -> int | None:
        try:
            return int(str(court_id).rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return None

    def _check_court(self, court_num) -> int:
        """Validate a court number against the configured court count."""
        n = int(court_num)
        count = self._court_count()
        if not 1 <= n <= count:
            raise ValueError(f"court {court_num} does not exist "
                             f"(this tournament has courts 1-{count})")
        return n

    def _center(self) -> set:
        """Center courts that exist and are enforced (shared rule; see
        schedule/courtplan.py). Empty => any court may host a knockout match."""
        return set(center_court_numbers(
            self.t.settings, range(1, self._court_count() + 1)))

    def _match_index(self):
        idx = {}
        for div_id, br in self.t.brackets.items():
            for m in br.matches.values():
                idx[m.id] = (div_id, m)
        return idx

    def _is_knockout(self, div_id, m) -> bool:
        """Whether a match must use a center court (shared rule; see
        schedule/courtplan.py): a knockout QF/SF/final only."""
        br = self.t.brackets.get(div_id)
        return bool(br and is_center_court_match(br, m))

    def _board_match_view(self, div_id, m) -> dict:
        return {
            "id": m.id, "division": div_id, "seq": m.seq,
            "division_label": self.t.divisions[div_id].label,
            "round": m.round_name, "part": m.bracket_part,
            "knockout": self._is_knockout(div_id, m),
            "side1": self._entry_view(m.side1), "side2": self._entry_view(m.side2),
            "games": m.result.games if m.result else [],
            "winner": (m.result.winner.key() if m.result and m.result.winner else None),
            "winner_label": (self.t.entry_label(m.result.winner)
                             if m.result and m.result.winner else ""),
            "score": " ".join(f"{a}-{b}" for a, b in m.result.games) if m.result else "",
            "max_games": 1 if self.t.brackets[div_id].format == "round_robin"
            else self.t.settings.match_format.best_of,
        }

    @staticmethod
    def _playable(m) -> bool:
        return bool(m.side1 and m.side2 and m.side1.kind in ("player", "pair")
                    and m.side2.kind in ("player", "pair") and not m.result)

    def board_view(self) -> dict:
        idx = self._match_index()
        count = self._court_count()
        # Prune stale assignments: a completed or vanished match frees its court,
        # and so does an assignment to a court number that no longer exists
        # (e.g. after the court count was lowered in Settings).
        with self._lock:
            for cid, mid in list(self.t.court_board.items()):
                num = self._court_num(cid)
                if (num is None or not 1 <= num <= count
                        or mid not in idx or idx[mid][1].result is not None):
                    del self.t.court_board[cid]
        assigned = dict(self.t.court_board)
        assigned_ids = set(assigned.values())

        # Players currently on ANY court. "Waiting" is global: if a player is on
        # a court, every match needing them is waiting on every court (so all
        # courts of the same type show an identical, consistent on-deck list).
        playing = set()
        for cid, mid in assigned.items():
            if mid in idx:
                playing |= match_player_ids(self.t, idx[mid][1])

        # Ready matches (playable, not on a court), ordered by the schedule if one
        # exists (that's the "ideal" order), else by division/seq.
        sched_pos = {b.match_id: b.start_min for b in self.t.schedule}
        ready = []
        for div_id, br in self.t.brackets.items():
            for m in br.matches.values():
                if self._playable(m) and m.id not in assigned_ids:
                    ready.append((div_id, m))
        ready.sort(key=lambda dm: (sched_pos.get(dm[1].id, 10 ** 9),
                                   dm[0], dm[1].seq))
        queue = [self._board_match_view(d, m) for d, m in ready]

        center = self._center()

        def court_ok(num, d, m):
            # QF/SF/final matches use the center courts when at least two of them
            # exist; every other match may use any court.
            return not self._is_knockout(d, m) or not center or num in center

        def is_ready(m):
            return not (match_player_ids(self.t, m) & playing)

        # Every court (busy or open) gets an "on deck" list: the next eligible
        # matches for it. Ready matches (players free right now) come FIRST so an
        # open court always surfaces something playable; center courts then
        # prefer knockout; ties fall back to the schedule/seq order.
        courts = []
        for num in range(1, count + 1):
            cid = f"court-{num}"
            mid = assigned.get(cid)
            elig = [(d, m) for d, m in ready if court_ok(num, d, m)]
            elig.sort(key=lambda dm: (
                0 if is_ready(dm[1]) else 1,                      # ready first
                (0 if self._is_knockout(dm[0], dm[1]) else 1) if num in center else 0,
                sched_pos.get(dm[1].id, 10 ** 9), dm[0], dm[1].seq))
            options = []
            for d, m in elig[:5]:
                mv = self._board_match_view(d, m)
                mv["ready"] = is_ready(m)
                options.append(mv)
            courts.append({
                "num": num, "id": cid, "center": num in center,
                "match": self._board_match_view(*idx[mid]) if mid and mid in idx else None,
                "options": options,
            })

        # Upcoming knockout: not-yet-playable knockout matches (a side is still a
        # pool/wildcard placeholder or awaiting a feeder). Shown as read-only
        # cards so the organizer sees the draw skeleton; they autofill as pools
        # finish and, once both sides are real, drop into the ready queue above.
        upcoming = []
        for div_id, br in self.t.brackets.items():
            for m in br.matches.values():
                if m.bracket_part == "pool":
                    continue
                if m.result and (m.result.winner or m.result.walkover):
                    continue
                if self._playable(m):
                    continue                       # already in the ready queue
                upcoming.append(self._board_match_view(div_id, m))
        upcoming.sort(key=lambda q: (q["division_label"], q["seq"]))

        completed = []
        for div_id, br in self.t.brackets.items():
            for m in br.matches.values():
                if m.result and m.result.winner and not m.result.walkover:
                    completed.append(self._board_match_view(div_id, m))
        completed.sort(key=lambda q: (q["division_label"], q["round"]))

        return {"courts": courts, "queue": queue, "upcoming": upcoming,
                "completed": completed, "center_courts": sorted(center)}

    def board_assign(self, court_num: int, match_id: str) -> dict:
        with self._lock:
            court_num = self._check_court(court_num)
            idx = self._match_index()
            if match_id not in idx:
                raise ValueError("no such match")
            div_id, m = idx[match_id]
            if not self._playable(m):
                raise ValueError("that match isn't ready to play")
            center = self._center()
            if self._is_knockout(div_id, m) and center and court_num not in center:
                allowed = ", ".join(str(c) for c in sorted(center))
                raise Conflict("knockout matches (QF/SF/final) can only go on the "
                               f"center courts {allowed}")
            cid = f"court-{court_num}"
            occupant = self.t.court_board.get(cid)
            if occupant and occupant != match_id:
                raise Conflict(f"court {court_num} is occupied; clear it first")
            # No double-booking: a player can't be on two courts at once.
            idxx = self._match_index()
            busy = set()
            for c, mm in self.t.court_board.items():
                if c != cid and mm in idxx:
                    busy |= match_player_ids(self.t, idxx[mm][1])
            if match_player_ids(self.t, m) & busy:
                raise Conflict("a player in this match is already on another court")
            # Remove this match from any other court, then place it here.
            for c, mm in list(self.t.court_board.items()):
                if mm == match_id:
                    del self.t.court_board[c]
            self.t.court_board[cid] = match_id
            self._save()
            return self.board_view()

    def board_clear(self, court_num: int) -> dict:
        with self._lock:
            court_num = self._check_court(court_num)
            self.t.court_board.pop(f"court-{court_num}", None)
            self._save()
            return self.board_view()

    def board_result(self, court_num: int, games: list[list[int]]) -> dict:
        with self._lock:
            court_num = self._check_court(court_num)
            cid = f"court-{court_num}"
            mid = self.t.court_board.get(cid)
            if not mid:
                raise ValueError("no match on that court")
            div_id, _m = self._match_index()[mid]
            self.record_result(div_id, mid, games)   # advances + frees below
            self.t.court_board.pop(cid, None)
            self._save()
            return self.board_view()

    def clear_match(self, division_id: str, match_id: str) -> dict:
        """Clear a single match's result (fix a wrong entry). Removes its winner
        from downstream slots and, for group play, re-evaluates which qualifiers
        fill the knockout."""
        with self._lock:
            br = self.t.brackets[division_id]
            m = br.matches.get(match_id)
            if m is None:
                raise ValueError("no such match")
            if m.result is not None:
                unpropagate(br, m)
                m.result = None
            div = self.t.divisions[division_id]
            if div.team_format and m.parent_id:
                tie.decide_tie(self.t, br, br.matches[m.parent_id])
                tie.fill_ties_from_draw(self.t, br, self.t.settings.multi_event_cap)
            elif br.format == "group_knockout":
                bracket_groups.fill_knockout_from_pools(self.t, br)
            self._save()
            return self.bracket_view(division_id)

    # --- scheduling ---------------------------------------------------------
    def _schedule_sig(self) -> str:
        """Signature of everything that affects scheduling; a change means the
        current schedule is stale. Includes the settings AND a fingerprint of
        each bracket (format, version, match count) so regenerating a bracket --
        e.g. adding the knockout draw -- flags the schedule for regeneration."""
        s = self.t.settings
        t, p = s.timing, s.pool_timing
        cc = ",".join(str(c) for c in s.center_courts)
        brackets = "|".join(
            f"{d}:{b.format}:{b.version}:{len(b.matches)}"
            for d, b in sorted(self.t.brackets.items()))
        return (f"c{s.court_count}|d{s.day_start}|r{s.rest_min}|x{cc}"
                f"|k{t.warmup_min},{t.play_min},{t.buffer_min}"
                f"|p{p.warmup_min},{p.play_min},{p.buffer_min}"
                f"|B{brackets}")

    def generate_schedule(self, division_ids: list[str] | None = None) -> dict:
        with self._lock:
            generate_schedule(self.t, self.t.settings, division_ids)
            self.t.schedule_sig = self._schedule_sig()
            self._save(backup=True)
            return self.schedule_view()

    def schedule_view(self) -> dict:
        day_start = self.t.settings.day_start
        match_div = {}
        titles = {}
        for div_id, br in self.t.brackets.items():
            for mid, m in br.matches.items():
                match_div[mid] = div_id
                titles[mid] = m.round_name
        rows = []
        for b in sorted(self.t.schedule, key=lambda x: (x.start_min, x.court_id)):
            div_id = match_div.get(b.match_id)
            br = self.t.brackets.get(div_id)
            m = br.matches.get(b.match_id) if br else None
            rows.append({
                "match_id": b.match_id, "court": b.court_id,
                "start": minutes_to_clock(day_start, b.start_min),
                "play_start": minutes_to_clock(day_start, b.play_start_min),
                "start_min": b.start_min,
                "division": self.t.divisions[div_id].label if div_id else "",
                "round": titles.get(b.match_id, ""),
                "side1": self._entry_view(m.side1) if m else None,
                "side2": self._entry_view(m.side2) if m else None,
            })
        # Simulation-mode estimate: when does the last court free up?
        end_min = max((b.start_min + self.t.settings.timing.slot_min
                       for b in self.t.schedule), default=0)
        stale = bool(self.t.schedule and self.t.schedule_sig
                     and self.t.schedule_sig != self._schedule_sig())
        return {"day_start": day_start, "slot_min": self.t.settings.timing.slot_min,
                "ends": minutes_to_clock(day_start, end_min) if self.t.schedule else "",
                "duration_min": end_min, "match_count": len(self.t.schedule),
                "conflicts": player_conflicts(self.t), "stale": stale, "blocks": rows}

    def best_dates(self) -> dict:
        return availability_report(self.t)

    # --- planner: compare formats with time estimates -----------------------
    def _estimate_makespan(self, div, br, settings: Settings) -> int:
        """Minutes of court time this bracket needs. Reuses the real scheduler
        on a throwaway tournament so player-rest and dependencies are honoured.
        For group_knockout the knockout runs *after* the pool stage."""
        def sched(matches: dict) -> int:
            temp = Tournament(players=self.t.players, pairs=self.t.pairs,
                              teams=self.t.teams, divisions={div.id: div},
                              brackets={div.id: Bracket(
                                  division_id=div.id, format=br.format,
                                  matches=matches, seeds=br.seeds)})
            blocks = generate_schedule(temp, settings, [div.id])
            return max((b.start_min + settings.timing.slot_min for b in blocks),
                       default=0)

        if div.team_format:
            return sched(br.matches)         # scheduler picks the rubbers itself
        if br.format == "group_knockout":
            pool = {k: m for k, m in br.matches.items() if m.bracket_part == "pool"}
            ko = {k: m for k, m in br.matches.items() if m.bracket_part != "pool"}
            return sched(pool) + sched(ko)      # KO follows the pool stage
        return sched(br.matches)

    def plan_division(self, division_id: str, start: str | None = None,
                      end: str | None = None, court_count: int | None = None,
                      method: str = "ranking", num_groups: int | None = None) -> dict:
        div = self.t.divisions[division_id]
        start = start or self.t.settings.day_start
        end = end or (self.t.settings.day_end or None)
        settings = self.t.settings.with_overrides(
            court_count=court_count or self.t.settings.court_count,
            day_start=start)
        seeds = seed_entries(self.t, div, method)
        n = len(seeds)
        is_team = bool(div.team_format)

        candidates = (self._team_plan_candidates(n) if is_team
                      else self._plan_candidates(n, num_groups))

        options = []
        for c in candidates:
            fmt, kw = c["format"], c["params"]
            entry = {k: c[k] for k in ("format", "params", "label", "combined",
                                       "recommended", "note")}
            try:
                if fmt == "group_knockout":
                    br = bracket_groups.generate(div, seeds, None,
                                                 kw.get("num_groups"),
                                                 kw.get("main_draw"))
                else:
                    br = format_registry.generate(fmt, div, seeds)
                if is_team:
                    tie.fill_ties_from_draw(self.t, br)      # expand ties -> rubbers
            except Exception as e:  # noqa: BLE001 - report as unavailable option
                options.append({**entry, "ok": False, "reason": str(e)})
                continue
            makespan = self._estimate_makespan(div, br, settings)
            end_abs = parse_clock(start) + makespan
            fits = end is None or end_abs <= parse_clock(end)
            opt = {
                **entry, "ok": True,
                "matches": sum(1 for m in br.matches.values()
                               if not (m.result and m.result.walkover)
                               and (m.bracket_part == "rubber" if is_team
                                    else True)),
                "rounds": len(br.rounds),
                "duration_min": makespan,
                "end_time": minutes_to_clock(start, makespan),
                "fits": fits,
                "overtime_min": max(0, end_abs - parse_clock(end)) if end else 0,
                "preview": self._view_of(div, br),
            }
            if is_team:
                opt["scoring"] = self._format_scoring_desc(div, fmt)
            options.append(opt)
        out = {"division": {"id": div.id, "event": div.event, "label": div.label},
               "entries": n, "start": start, "end": end,
               "courts": settings.court_count,
               "slot_min": settings.timing.slot_min, "options": options,
               "team": is_team}
        if is_team:
            tf = div.team_format
            out["team_format"] = {
                "events": tf.events, "rank_by": tf.rank_by,
                "allow_draw": tf.allow_draw, "dead_rubbers": tf.dead_rubbers,
                "play_mode": tf.play_mode, "win_points": tf.win_points,
                "draw_points": tf.draw_points, "loss_points": tf.loss_points,
                "tie_format": tf.tie_format, "match_length": tf.match_length,
                "handicap": tf.handicap, "event_rules": tf.event_rules}
            out["scoring_note"] = self._point_system_desc(div)
        return out

    # --- team scoring descriptions -----------------------------------------
    def _rank_desc(self, tf) -> str:
        if tf.rank_by == "league_points":
            return (f"league points (win {tf.win_points}"
                    + (f" / draw {tf.draw_points}" if tf.allow_draw else "")
                    + f" / loss {tf.loss_points})")
        if tf.rank_by == "rubbers":
            return "total rubbers won"
        if tf.rank_by == "points":
            return "total points scored"
        return "ties won"

    def _tie_desc(self, tf) -> str:
        if tf.tie_format == "cross":
            base = ("every entry plays every opposing entry in each event "
                    "(round-robin within the tie); most matches won wins")
        else:
            base = ("entries are matched by rank (#1 v #1, #2 v #2, ...); "
                    "most matches won wins the tie")
        length = ("full best-of-3 matches" if tf.match_length != "quick"
                  else "quick single timed games")
        extra = " Handicap on: the lower-rated side gets a per-game head start." if tf.handicap else ""
        rules = ""
        if tf.event_rules:
            rules = " Per-event: " + ", ".join(f"{e}={v}" for e, v in tf.event_rules.items()) + "."
        return f"{base} ({length}).{extra}{rules}"

    def _point_system_desc(self, div) -> str:
        tf = div.team_format
        draw = ("A tie can end level (draw)." if tf.allow_draw
                else "Level ties are broken by games, then points.")
        return (f"Tie: {self._tie_desc(tf)} {draw} Standings rank teams by "
                f"{self._rank_desc(tf)}, then rubber differential, then point "
                f"differential. Events: {', '.join(tf.events)}. Rubbers play "
                f"{tf.play_mode}"
                f"{'; dead rubbers skipped at clinch' if tf.dead_rubbers == 'stop' else '; all rubbers played'}.")

    def _format_scoring_desc(self, div, fmt) -> str:
        rank = self._rank_desc(div.team_format)
        if fmt == "round_robin":
            return f"League: every team plays every team; ranked by {rank}."
        if fmt == "group_knockout":
            return f"Pools ranked by {rank}; top teams advance to a knockout of teams."
        if fmt == "double_elim":
            return "Knockout of teams with a losers bracket (second chance)."
        return "Straight knockout of teams; win your tie to advance."

    def _team_plan_candidates(self, n: int) -> list[dict]:
        """Team-appropriate format menu (draws are over teams; byes are fine)."""
        def mk(fmt, params, label, recommended, note):
            return {"format": fmt, "params": params, "label": label,
                    "combined": fmt == "group_knockout", "recommended": recommended,
                    "note": note}
        out = [mk("single_elim", {}, "Single elimination", n > 6,
                  "Knockout of teams; lose a tie and you're out.")]
        if n >= 4:
            out.append(mk("double_elim", {}, "Double elimination", False,
                          "Knockout with a losers bracket (second chance)."))
        out.append(mk("round_robin", {}, "Round robin (league / point system)",
                      n <= 6, "Every team plays every team; winner by standings."))
        if n >= 4:
            out.append(mk("group_knockout", {"num_groups": 2 if n <= 8 else 4},
                          "Pools -> knockout", False,
                          "Group stage, then the top teams into a knockout."))
        return out

    def _plan_candidates(self, n: int, num_groups: int | None = None) -> list[dict]:
        """Build the format menu. Every option resolves to a power-of-two
        knockout; when the field isn't a power of two, a group/round-robin stage
        trims it to a clean draw (the recommended, no-bye strategy). If
        ``num_groups`` is given, the group options use exactly that many pools."""
        from ..engine.bracket_groups import largest_pow2_le, resolve_group_plan
        from ..engine.seeding import next_power_of_two

        def mk(fmt, params, label, combined, recommended, note):
            return {"format": fmt, "params": params, "label": label,
                    "combined": combined, "recommended": recommended, "note": note}

        def gk_note(g, m, base, wild):
            """Human summary of how a group->knockout draw is filled (no byes):
            top-`base` per pool guaranteed, rest by best-remaining points."""
            guaranteed = base * g
            who = (f"top {base} of each pool ({guaranteed})" if base
                   else "no automatic qualifiers")
            if wild:
                return (f"{g} pools -> {who}, plus the {wild} best-remaining by "
                        f"points -> clean {m}-draw (no byes).")
            return f"{g} pools -> {who} -> clean {m}-draw (no byes)."

        def add_group_options(g_fixed):
            """Offer the largest clean draw and a tighter half-size draw, both
            filled entirely with real teams via the base + wildcard model."""
            first = True
            for m in (largest_pow2_le(n - 1 if is_pow2 else n),):
                for mm in (m, m // 2):
                    if mm < 2:
                        continue
                    g, drawn, base, wild = resolve_group_plan(n, g_fixed, mm)
                    if drawn != mm:              # already offered this draw size
                        continue
                    label = f"{g} pools -> {drawn}-draw knockout"
                    recommended = (g_fixed is None and not is_pow2 and first)
                    note = gk_note(g, drawn, base, wild)
                    if not first:
                        note = "Tighter (shorter day): " + note
                    out.append(mk("group_knockout",
                                  {"num_groups": g, "main_draw": drawn},
                                  label, True, recommended, note))
                    first = False

        out: list[dict] = []
        if n < 2:
            return out
        is_pow2 = (n & (n - 1)) == 0

        # If the organizer fixed a pool count, offer group options for it plus
        # the pure formats, and return early (their explicit choice wins).
        if num_groups and 1 <= num_groups <= n:
            add_group_options(num_groups)
            out.append(mk("single_elim", {}, "Single elimination"
                          + ("" if is_pow2 else " (with byes)"), False, False,
                          "Straight knockout of the whole field."))
            out.append(mk("round_robin", {}, "Round robin", False, False,
                          "Everyone plays everyone; winner by standings."))
            return out

        # --- Pure knockout / round robin (always listed) ---
        if is_pow2:
            out.append(mk("single_elim", {}, "Single elimination", False, True,
                          f"Clean {n}-draw knockout, no byes."))
        else:
            byes = next_power_of_two(n) - n
            out.append(mk("single_elim", {}, "Single elimination (with byes)",
                          False, False,
                          f"Straight knockout padded to a {next_power_of_two(n)}-draw "
                          f"with {byes} bye{'s' if byes != 1 else ''}."))
        if n >= 4:
            de_note = ("Losers bracket gives a second chance." if is_pow2 else
                       "Losers bracket gives a second chance; top seeds get byes.")
            out.append(mk("double_elim", {}, "Double elimination", False, False, de_note))
        out.append(mk("round_robin", {}, "Round robin", False, False,
                      "Everyone plays everyone; winner by standings (no knockout)."))

        # --- Group / round-robin -> a clean power-of-two knockout (no byes) ---
        add_group_options(None)
        return out

    # --- CSV export ---------------------------------------------------------
    def export_csv(self, what: str) -> tuple[str, str]:
        from ..export.csv_out import rows_to_csv

        if what == "roster":
            headers = ["Name", "Gender", "Skill", "Events", "Club",
                       "Willing random", "Withdrawn", "Placeholder"]
            rows = [[p["name"], p["gender"], p["skill"] if p["skill"] is not None else "",
                     " ".join(p["events"]), p["club"], p["willing_random"],
                     p["withdrawn"], p["stub"]] for p in self.players()]
            return "roster.csv", rows_to_csv(headers, rows)

        if what in ("schedule_time", "schedule_court"):
            view = self.schedule_view()
            rows = [[b["start"], b["court"], b["division"], b["round"],
                     (b["side1"] or {}).get("label", ""),
                     (b["side2"] or {}).get("label", "")]
                    for b in view["blocks"]]
            if what == "schedule_court":
                rows.sort(key=lambda r: (r[1], r[0]))
            return (f"{what}.csv",
                    rows_to_csv(["Time", "Court", "Division", "Round",
                                 "Side 1", "Side 2"], rows))

        if what == "standings":
            headers = ["Division", "Pool", "Rank", "Entry", "W", "L",
                       "Game +/-", "Points For", "Points Against", "Point +/-",
                       "Advances"]
            rows = []
            for div_id, br in self.t.brackets.items():
                if not br.pools:
                    continue
                for pv in all_standings(self.t, br):
                    for r in pv["rows"]:
                        rows.append([self.t.divisions[div_id].label, pv["pool"],
                                     r["rank"], r["label"], r["wins"], r["losses"],
                                     r["game_diff"], r["points_for"],
                                     r["points_against"], r["point_diff"],
                                     "yes" if r["advances"] else ""])
            return "standings.csv", rows_to_csv(headers, rows)

        if what == "results":
            headers = ["Division", "Round", "Side 1", "Side 2", "Score", "Winner"]
            rows = []
            for div_id, br in self.t.brackets.items():
                for m in br.matches.values():
                    if not m.result or not m.result.winner:
                        continue
                    score = " ".join(f"{a}-{b}" for a, b in m.result.games)
                    rows.append([self.t.divisions[div_id].label, m.round_name,
                                 self.t.entry_label(m.side1) if m.side1 else "",
                                 self.t.entry_label(m.side2) if m.side2 else "",
                                 score or ("W/O" if m.result.walkover else ""),
                                 self.t.entry_label(m.result.winner)])
            return "results.csv", rows_to_csv(headers, rows)

        raise ValueError(f"unknown export {what!r}")

    # --- views --------------------------------------------------------------
    def bracket_view(self, division_id: str) -> dict:
        div = self.t.divisions[division_id]
        br = self.t.brackets.get(division_id)
        if br is None:
            return {"division": {"id": div.id, "event": div.event,
                                 "label": div.label, "format": div.format},
                    "exists": False, "rounds": []}
        return self._view_of(div, br)

    def _view_of(self, div, br) -> dict:
        seed_by_key = {s.entry.key(): s.seed_no for s in br.seeds}
        best_of = self.t.settings.match_format.best_of
        is_team = bool(div.team_format)

        def sv(ref):
            ev = self._entry_view(ref)
            if ev:
                ev["seed"] = seed_by_key.get(ref.key())
            return ev

        rubber_max = (1 if (div.team_format and div.team_format.match_length == "quick")
                      else best_of)

        def is_playable(mm) -> bool:
            """Both sides are real entrants (not pool/wildcard placeholders)."""
            return _playable_side(mm.side1) and _playable_side(mm.side2)

        def is_phantom(m) -> bool:
            """The double-elim reset game only becomes a real match if the
            loser-bracket finalist wins the first grand final; until then it has
            no sides, so don't render an empty card for it."""
            return bracket_double.is_inactive_reset(m)

        def rubber_view(rid):
            r = br.matches[rid]
            label = r.round_name.split("·")[-1].strip() if "·" in r.round_name else r.round_name
            return {"id": r.id, "label": label,
                    "side1": sv(r.side1), "side2": sv(r.side2),
                    "winner": (r.result.winner.key()
                               if r.result and r.result.winner else None),
                    "games": r.result.games if r.result else [],
                    "walkover": r.result.walkover if r.result else False,
                    "ready": is_playable(r), "max_games": rubber_max}

        rounds = []
        for rnd in br.rounds:
            matches = []
            for mid in rnd.match_ids:
                m = br.matches[mid]
                if is_phantom(m):
                    continue
                matches.append({
                    "id": m.id, "round": m.round_name, "part": m.bracket_part,
                    "seq": m.seq, "side1": sv(m.side1), "side2": sv(m.side2),
                    "winner": (m.result.winner.key()
                               if m.result and m.result.winner else None),
                    "games": m.result.games if m.result else [],
                    "walkover": m.result.walkover if m.result else False,
                    # Only a resolved walkover is a true "Bye"; a single-sided
                    # match with no result is TBD (opponent not yet decided).
                    "is_bye": bool(m.result and m.result.walkover),
                    "ready": is_playable(m),
                    # Only a standalone round-robin is a single timed game (1
                    # box). Group-stage pools and knockouts are best-of-N.
                    "max_games": 1 if br.format == "round_robin" else best_of,
                    # Team tie: nest its rubbers + the running rubber tally +
                    # any entries with no opponent (uneven event counts).
                    "is_tie": is_team,
                    "rubbers": [rubber_view(rid) for rid in m.sub_match_ids],
                    "tally": self._live_tally(br, m) if is_team else None,
                    "gaps": tie.tie_gaps(self.t, m) if (is_team and m.side1 and m.side2
                                                        and m.side1.kind == "team") else [],
                })
            rounds.append({"name": rnd.name, "part": rnd.bracket_part,
                           "matches": matches})

        # Current / up-next queue driven by results + bracket readiness (not
        # clock time): "ready" = playable now; "upcoming" = opens once the
        # matches feeding it are done or in progress.
        feeders: dict[str, list[str]] = {mid: [] for mid in br.matches}
        for mm in br.matches.values():
            for nxt in (mm.next_win_match, mm.next_lose_match):
                if nxt in feeders:
                    feeders[nxt].append(mm.id)

        def is_done(mm):
            return bool(mm.result and mm.result.winner)

        def summary(mm):
            return {"id": mm.id, "round": mm.round_name, "part": mm.bracket_part,
                    "side1": sv(mm.side1), "side2": sv(mm.side2)}

        ready, upcoming = [], []
        for mm in br.matches.values():
            if is_team:
                # In team mode the playable units are RUBBERS; ties are decided
                # by their rubbers, never played directly. Skip dead rubbers of a
                # clinched tie under the 'stop' policy.
                if mm.bracket_part != "rubber":
                    continue
                parent = br.matches.get(mm.parent_id)
                if (parent and parent.result and parent.result.winner
                        and div.team_format.dead_rubbers == "stop"):
                    continue
            # Skip resolved byes/walkovers and finished matches. A one-sided
            # match (a bye-advanced player awaiting an opponent) is NOT a bye --
            # it belongs in "upcoming".
            if (mm.result and mm.result.walkover) or is_done(mm):
                continue
            if is_playable(mm):
                ready.append(mm)
            else:
                fs = feeders.get(mm.id, [])
                if fs and all(is_done(br.matches[f]) or
                              (br.matches[f].side1 and br.matches[f].side2)
                              for f in fs):
                    upcoming.append(mm)
        queue = {"ready": [summary(m) for m in sorted(ready, key=lambda x: x.seq)],
                 "upcoming": [summary(m) for m in sorted(upcoming, key=lambda x: x.seq)]}

        return {
            "division": {"id": div.id, "event": div.event, "label": div.label,
                         "format": div.format},
            "exists": True, "finalized": br.finalized, "version": br.version,
            "queue": queue,
            "champion": self._entry_view(
                bracket_double.champion(br) if br.format == "double_elim"
                else champion(br)),
            "seeds": [{"seed_no": s.seed_no, "label": self.t.entry_label(s.entry)}
                      for s in br.seeds],
            "standings": self._standings_view(br),
            "team_rosters": self._team_rosters_view(div, br) if is_team else [],
            "rounds": rounds,
        }

    def _live_tally(self, br, tie) -> list | None:
        """Running rubbers-won [side1, side2] for a tie, from played rubbers."""
        if not tie.sub_match_ids:
            return None
        w1 = w2 = 0
        for rid in tie.sub_match_ids:
            rm = br.matches.get(rid)
            if rm and rm.result and rm.result.winner:
                if rm.result.winner == rm.side1:
                    w1 += 1
                else:
                    w2 += 1
        return [w1, w2]

    def _team_rosters_view(self, div, br) -> list[dict]:
        """Per-team roster with each player's rubber win-loss record (drill-down
        under the team standings)."""
        rec: dict[str, list[int]] = {}          # player id -> [wins, losses]
        for m in br.matches.values():
            if m.bracket_part != "rubber" or not (m.result and m.result.winner):
                continue
            win, lose = m.result.winner, (m.side2 if m.result.winner == m.side1
                                          else m.side1)
            for ref, delta in ((win, 0), (lose, 1)):
                if ref is None:
                    continue
                for pid in self._players_of(ref):
                    rec.setdefault(pid, [0, 0])[delta] += 1
        out = []
        for ref in div.entry_refs:
            team = self.t.teams.get(ref.ref_id)
            if not team:
                continue
            players = []
            for pid in team.player_ids:
                p = self.t.players.get(pid)
                w, l = rec.get(pid, [0, 0])
                players.append({"id": pid, "name": p.full if p else pid,
                                "wins": w, "losses": l})
            out.append({"team_id": team.id, "name": team.name,
                        "color": team.color, "players": players})
        return out

    def _players_of(self, ref) -> list[str]:
        if ref.kind == "player":
            return [ref.ref_id]
        if ref.kind == "pair":
            pair = self.t.pairs.get(ref.ref_id)
            return list(pair.player_ids) if pair else []
        return []

    def _standings_view(self, br) -> list[dict]:
        """Pool standings, annotated for group_knockout with each row's live
        qualification status: 'auto' (guaranteed top-of-pool), 'wildcard'
        (currently projected to fill a wildcard slot) or 'out'. Recomputed here,
        so it updates every time a score is reported."""
        if not br.pools:
            return []
        div = self.t.divisions.get(br.division_id)
        if div and div.team_format:
            from ..engine.team_standings import all_team_standings
            return all_team_standings(self.t, br, div.team_format)
        standings = all_standings(self.t, br)
        if br.format == "group_knockout":
            cls = bracket_groups.project_qualifiers(self.t, br)
            for pv in standings:
                for r in pv["rows"]:
                    r["qualify"] = cls.get(r["key"], "out")
        return standings

    def public_snapshot(self) -> dict:
        return {
            "name": self.t.name,
            "divisions": [self.bracket_view(d.id) for d in
                          sorted(self.t.divisions.values(), key=lambda x: x.event)
                          if self.t.brackets.get(d.id)],
        }
