"""The clean team-form flow: Player 2's gender is inferred from the event (the
form only asks P1's gender), and a person re-collected for a secondary event is
deduped into one player with both events."""

import os
import tempfile
import unittest

from tournament.server.service import TournamentService
from tournament.store.repository import Repository

HEADERS = ("Event,Club,Player 1 First Name,Player 1 Last Name,Player 1 Email,"
           "Player 1 Gender,Player 1 Skill,Player 2 First Name,Player 2 Last Name,"
           "Player 2 Email,Player 2 Gender,Player 2 Skill")

CSV = "\n".join([
    HEADERS,
    # XD: Bob (M) + Alice (gender blank -> inferred F)
    "Mixed Doubles (XD),BYU,Bob,Kae,bob@x.com,Male,7,Alice,Lin,alice@x.com,,6",
    # Secondary MD: same Bob (same email) + Carl (blank -> inferred M)
    "Men's Doubles (MD),BYU,Bob,Kae,bob@x.com,Male,7,Carl,Ng,carl@x.com,,6",
])


class TestTeamIngest(unittest.TestCase):
    def test_inference_and_dedup(self):
        d = tempfile.TemporaryDirectory()
        svc = TournamentService(Repository(os.path.join(d.name, "t.json")))
        svc.import_preview("text", CSV, "auto")
        svc.import_commit()
        by_name = {p.full: p for p in svc.t.players.values()}
        # Bob appears once, carrying both events.
        bobs = [p for p in svc.t.players.values() if p.email == "bob@x.com"]
        self.assertEqual(len(bobs), 1)
        self.assertEqual(sorted(bobs[0].events), ["MD", "XD"])
        # Inferred genders for the partners whose gender the form omitted.
        self.assertEqual(by_name["Alice Lin"].gender, "F")   # XD partner of a man
        self.assertEqual(by_name["Carl Ng"].gender, "M")     # MD partner
        d.cleanup()

    def test_team_build_after_import_materializes_pairs(self):
        # Reproduces the reported bug: import (no build_divisions), then build a
        # doubles team event -> pairs must be materialized so entries exist.
        rows = [HEADERS]
        for i in range(8):
            rows.append(f"Mixed Doubles (XD),BYU,Bob{i},K,bob{i}@x.com,Male,7,"
                        f"Amy{i},L,amy{i}@x.com,,6")
        d = tempfile.TemporaryDirectory()
        svc = TournamentService(Repository(os.path.join(d.name, "t.json")))
        svc.import_preview("text", "\n".join(rows), "auto")
        svc.import_commit()
        self.assertEqual(svc.t.pairs, {})            # no pairs yet (no grouping run)
        pv = svc.team_preview({"method": "balanced", "num_teams": 4,
                               "team_type": "mixed", "template": {"events": ["XD"]},
                               "rng_seed": 1})
        self.assertEqual(len(pv["teams"]), 4)        # not 1!
        total = sum(t["size"] for t in pv["teams"])
        self.assertEqual(total, 8)                   # all 8 XD pairs became entries
        r = svc.commit_teams({"method": "balanced", "num_teams": 4,
                              "team_type": "mixed", "template": {"events": ["XD"]},
                              "rng_seed": 1})
        self.assertEqual(r["teams"], 4)
        d.cleanup()


if __name__ == "__main__":
    unittest.main()
