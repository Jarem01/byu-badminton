"""Import orchestration: source rows -> Tournament + resolution issues.

Ties together adapter selection, fuzzy partner resolution, and stub-player
creation. Produces a Tournament (players + registrations) plus the issues that
arise from *resolution* (typos, unresolved names, ambiguity). Cross-entity
data-quality checks live in ``validate.dashboard``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model.entities import Player, Tournament
from ..model.ids import IdFactory
from .adapters import pick_adapter
from ..ingest.normalize import name_key
from ..validate.fuzzy import AUTO_THRESHOLD, NameResolver
from ..validate.issues import Issue
from .partner_parse import looks_like_name


@dataclass(slots=True)
class ImportResult:
    tournament: Tournament
    issues: list[Issue] = field(default_factory=list)
    adapter: str = ""

    @property
    def stats(self) -> dict:
        return {
            "players": len([p for p in self.tournament.players.values() if not p.is_stub]),
            "stub_players": len([p for p in self.tournament.players.values() if p.is_stub]),
            "registrations": len(self.tournament.registrations),
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warning"),
        }


def build_tournament(headers: list[str], rows: list[dict], schema: str = "auto",
                     name: str = "BYU Badminton Tournament") -> ImportResult:
    adapter = pick_adapter(headers, schema)
    ids = IdFactory()
    players, regs = adapter.build(rows, ids)

    resolver = NameResolver(players)
    issues: list[Issue] = []
    stub_by_name: dict[str, str] = {}

    for reg in regs:
        for hint in reg.partner_hints:
            if hint.resolved_player_id:      # strict adapter pre-resolves
                continue
            res = resolver.resolve(hint.raw_name)
            hint.confidence = res.confidence
            if res.player_id and res.confidence >= AUTO_THRESHOLD:
                hint.resolved_player_id = res.player_id
                if res.confidence < 1.0:
                    issues.append(Issue(
                        "info", "partner_typo_autofixed",
                        f"Row {reg.row_index}: matched partner '{hint.raw_name}' "
                        f"to '{players[res.player_id].full}' "
                        f"({res.confidence:.0%}).",
                        target=f"row:{reg.row_index}"))
            elif res.ambiguous:
                issues.append(Issue(
                    "warning", "partner_ambiguous",
                    f"Row {reg.row_index}: partner '{hint.raw_name}' is ambiguous "
                    f"(multiple people share that first name). Specify a full name.",
                    target=f"row:{reg.row_index}", suggestion=res.suggestion or ""))
            elif res.suggestion:
                issues.append(Issue(
                    "warning", "partner_maybe_typo",
                    f"Row {reg.row_index}: partner '{hint.raw_name}' not found. "
                    f"Did you mean '{res.suggestion}'? ({res.confidence:.0%})",
                    target=f"row:{reg.row_index}", suggestion=res.suggestion))
            elif looks_like_name(hint.raw_name):
                # Genuinely new person only mentioned as a partner -> stub.
                key = name_key(hint.raw_name)
                sid = stub_by_name.get(key)
                if not sid:
                    parts = hint.raw_name.split()
                    sid = ids.make("player", *parts)
                    players[sid] = Player(
                        id=sid, first=parts[0],
                        last=" ".join(parts[1:]),
                        gender="U", skill=None, is_stub=True,
                        events=[hint.event_hint] if hint.event_hint else [])
                    stub_by_name[key] = sid
                    issues.append(Issue(
                        "warning", "partner_stub_created",
                        f"Row {reg.row_index}: partner '{hint.raw_name}' has no "
                        f"registration. Created a placeholder — enter skill/"
                        f"gender or link to a real player.",
                        target=f"player:{sid}"))
                hint.resolved_player_id = sid
            else:
                issues.append(Issue(
                    "warning", "partner_unparseable",
                    f"Row {reg.row_index}: could not read a partner name from "
                    f"'{hint.raw_name}'.", target=f"row:{reg.row_index}"))

    tournament = Tournament(name=name, players=players, registrations=regs)
    return ImportResult(tournament=tournament, issues=issues, adapter=adapter.name)
