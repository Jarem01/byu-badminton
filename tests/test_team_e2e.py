"""End-to-end (entry-based) on the messy-mix registration + HTTP smoke +
individual regression."""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request

from tournament.model.entities import Pair, Player
from tournament.server.app import make_server
from tournament.server.service import TournamentService
from tournament.store.repository import Repository


def messy_service(path=None):
    svc = TournamentService(Repository(path or os.path.join(tempfile.mkdtemp(), "t.json")))
    t = svc.t
    for i in range(12):                       # 12 XD pairs
        m, w = f"xm{i}", f"xw{i}"
        t.players[m] = Player(id=m, first=f"XM{i}", last="X", gender="M", skill=9 - i % 8, events=["XD"])
        t.players[w] = Player(id=w, first=f"XW{i}", last="Y", gender="F", skill=9 - i % 8, events=["XD"])
        t.pairs[f"px{i}"] = Pair(id=f"px{i}", player_ids=[m, w], event="XD")
    for i in range(4):                        # 4 MD pairs
        a, b = f"md{i}a", f"md{i}b"
        t.players[a] = Player(id=a, first=f"MDA{i}", last="Z", gender="M", skill=7, events=["MD"])
        t.players[b] = Player(id=b, first=f"MDB{i}", last="Z", gender="M", skill=6, events=["MD"])
        t.pairs[f"pmd{i}"] = Pair(id=f"pmd{i}", player_ids=[a, b], event="MD")
    for i in range(8):                        # 8 MS singles
        t.players[f"ms{i}"] = Player(id=f"ms{i}", first=f"MS{i}", last="S", gender="M", skill=5, events=["MS"])
    for i in range(2):                        # 2 WS singles
        t.players[f"ws{i}"] = Player(id=f"ws{i}", first=f"WS{i}", last="S", gender="F", skill=5, events=["WS"])
    return svc


OPTS = {"method": "balanced", "num_teams": 4, "team_type": "mixed",
        "template": {"events": ["MS", "WS", "MD", "XD"]}, "rng_seed": 3}


class TestMessyMix(unittest.TestCase):
    def test_no_player_dropped_and_pairs_together(self):
        svc = messy_service()
        self.assertEqual(len(svc.t.players), 42)
        r = svc.commit_teams(OPTS)
        div = svc.t.divisions[r["id"]]
        home = {pid: ref.ref_id for ref in div.entry_refs
                for pid in svc.t.teams[ref.ref_id].player_ids}
        self.assertEqual(sorted(home), sorted(svc.t.players))     # nobody dropped
        for pair in svc.t.pairs.values():
            a, b = pair.player_ids
            self.assertEqual(home[a], home[b])                   # pairs intact

    def test_entries_used_intact_in_rubbers(self):
        svc = messy_service()
        r = svc.commit_teams(OPTS)
        svc.generate_bracket(r["id"], "single_elim")
        br = svc.t.brackets[r["id"]]
        pair_ids = set(svc.t.pairs)
        checked = 0
        for m in br.matches.values():
            if m.bracket_part != "rubber":
                continue
            for side in (m.side1, m.side2):
                if side and side.kind == "pair":
                    self.assertIn(side.ref_id, pair_ids)          # a registered pair, not ad-hoc
                    checked += 1
        self.assertGreater(checked, 0)

    def test_report_grid_flags_gaps(self):
        svc = messy_service()
        pv = svc.team_preview(OPTS)
        self.assertEqual(len(pv["report"]["grid"]), 4)
        # WS (only 2 singles) across 4 teams is necessarily uneven -> a gap.
        self.assertTrue(pv["report"]["gaps"])


class TestHttpSmoke(unittest.TestCase):
    def test_team_endpoints(self):
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        svc = messy_service(path)
        svc.t.mode = "team"
        svc._save()                     # the server reads the file
        httpd, _ = make_server(path, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.2)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(p, o):
            req = urllib.request.Request(base + p, data=json.dumps(o).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=20))

        def get(p):
            return json.load(urllib.request.urlopen(base + p, timeout=10))
        try:
            self.assertEqual(post("/api/mode", {"mode": "team"})["mode"], "team")
            self.assertEqual(get("/api/mode")["mode"], "team")
            pv = post("/api/teams/preview",
                      {"method": "balanced", "num_teams": 2, "team_type": "mixed",
                       "template": {"events": ["XD"]}})
            self.assertIn("teams", pv)
            self.assertIn("report", pv)
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestIndividualRegression(unittest.TestCase):
    def test_individual_flow_unchanged(self):
        svc = TournamentService(Repository(os.path.join(tempfile.mkdtemp(), "t.json")))
        self.assertEqual(svc.t.mode, "individual")
        fixture = os.path.join(os.path.dirname(__file__), "..", "sample_data",
                               "clean_singles_16.csv")
        svc.import_preview("file", os.path.abspath(fixture), "auto")
        svc.import_commit()
        svc.build_divisions(rng_seed=1)
        ms = next(x for x in svc.divisions() if x["event"] == "MS")
        view = svc.generate_bracket(ms["id"], "single_elim")
        self.assertTrue(view["exists"])
        self.assertFalse(view["rounds"][0]["matches"][0].get("is_tie"))


if __name__ == "__main__":
    unittest.main()
