"""M5: service-layer end-to-end (import -> validate -> group -> bracket ->
result), including the finalize-overwrite guard."""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request

from tournament.model.entities import Division, EntryRef, Pair, Player
from tournament.server.app import make_server
from tournament.server.service import Conflict, TournamentService
from tournament.store.repository import Repository

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "messy_legacy.csv")


class TestGenerateEndpointParams(unittest.TestCase):
    """The /api/bracket/generate HTTP endpoint must forward num_groups/advance
    (regression: it dropped them, so every group_knockout used the default)."""

    def test_generate_endpoint_honors_pool_config(self):
        d = tempfile.mkdtemp()
        httpd, port = make_server(os.path.join(d, "t.json"), port=0)
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
            post("/api/import", {"source": "file", "ref": os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "sample_data",
                             "clean_singles_16.csv"))})
            post("/api/import/commit", {})
            post("/api/divisions/build", {"rng_seed": 1})
            ms = next(x for x in get("/api/divisions")["divisions"]
                      if x["event"] == "MS")
            v = post("/api/bracket/generate",
                     {"division": ms["id"], "format": "group_knockout",
                      "method": "ranking", "num_groups": 4, "main_draw": 8})
            self.assertEqual(len(v["standings"]), 4)   # honored 4 pools, not default
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestRunOrderEndpoint(unittest.TestCase):
    """The organizer can put the events in the order they want scheduled."""

    def test_move_endpoint_reorders_and_keeps_the_choice(self):
        d = tempfile.mkdtemp()
        httpd, port = make_server(os.path.join(d, "t.json"), port=0)
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
            post("/api/import", {"source": "file", "ref": os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "sample_data",
                             "legacy_mixed.csv"))})
            post("/api/import/commit", {})
            post("/api/divisions/build", {"rng_seed": 1})
            divs = get("/api/divisions")["divisions"]
            self.assertEqual([x["sort_no"] for x in divs], list(range(len(divs))))
            xd = next(x for x in divs if x["event"] == "XD")
            for _ in range(len(divs)):                 # walk XD to the front
                post("/api/division/move", {"division": xd["id"], "delta": -1})
            order = [x["event"] for x in get("/api/divisions")["divisions"]]
            self.assertEqual(order[0], "XD")
            # A rebuild keeps the run order instead of resetting it.
            post("/api/divisions/build", {"rng_seed": 1})
            order2 = [x["event"] for x in get("/api/divisions")["divisions"]]
            self.assertEqual(order2[0], "XD")
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestLeagueChampion(unittest.TestCase):
    """A pure round robin has no final to win, so once every match is played the
    leader of the table is the champion (it used to show nobody)."""

    def test_league_leader_is_champion_once_complete(self):
        d = tempfile.mkdtemp()
        svc = TournamentService(Repository(os.path.join(d, "t.json")))
        r = svc.create_custom_division("League", "player",
                                       [f"P{i}:{5 - i}" for i in range(4)], "MS")
        svc.generate_bracket(r["id"], "round_robin")
        br = svc.t.brackets[r["id"]]
        self.assertIsNone(svc.bracket_view(r["id"])["champion"])   # nothing decided
        for m in list(br.matches.values()):
            first_wins = m.side1.key() < m.side2.key()
            svc.record_result(r["id"], m.id,
                              [[21, 15], [21, 18]] if first_wins
                              else [[15, 21], [18, 21]])
        view = svc.bracket_view(r["id"])
        top = view["standings"][0]["rows"][0]
        self.assertEqual(top["rank"], 1)
        self.assertEqual(view["champion"]["label"], top["label"])


class TestServiceFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        repo = Repository(os.path.join(self.dir.name, "tournament.json"))
        self.svc = TournamentService(repo, actor="tester@byu.edu")

    def tearDown(self):
        self.dir.cleanup()

    def test_import_preview_then_commit(self):
        prev = self.svc.import_preview("file", FIXTURE, "auto")
        self.assertEqual(prev["adapter"], "legacy")
        self.assertGreater(prev["stats"]["registrations"], 15)
        # Preview must NOT have committed yet.
        self.assertEqual(len(self.svc.t.players), 0)
        self.svc.import_commit()
        self.assertGreater(len(self.svc.t.players), 15)

    def test_import_commit_keeps_settings_and_mode(self):
        # Re-importing replaces the roster, never the organizer's configuration
        # (previously commit swapped in a fresh doc with DEFAULT_SETTINGS).
        self.svc.update_settings({"court_count": 6, "day_start": "09:00",
                                  "play_min": 45})
        self.svc.set_mode("team")
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        s = self.svc.get_settings()
        self.assertEqual(s["court_count"], 6)
        self.assertEqual(s["day_start"], "09:00")
        self.assertEqual(s["play_min"], 45)
        self.assertEqual(self.svc.t.mode, "team")

    def test_inline_fix_during_preview_survives_commit(self):
        # A gender/skill fix made on the preview must persist through commit
        # (previously commit overwrote it with the original preview).
        self.svc.import_preview("file", FIXTURE, "auto")
        target = next(p for p in self.svc.players() if p["skill"] is None
                      or p["gender"] == "U")
        pid = target["id"]
        self.svc.override(f"player:{pid}", "skill", "6")
        self.svc.override(f"player:{pid}", "gender", "M")
        self.svc.import_commit()
        p = self.svc.t.players[pid]
        self.assertEqual(p.skill, 6)
        self.assertEqual(p.gender, "M")

    def test_full_pipeline_and_finalize_guard(self):
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=2026)
        divs = self.svc.divisions()
        ms = next(d for d in divs if d["event"] == "MS")

        view = self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        self.assertTrue(view["exists"])
        self.assertTrue(view["rounds"])

        # Finalize, then a re-generate without force must 409-style raise.
        self.svc.finalize(ms["id"])
        with self.assertRaises(Conflict):
            self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        # With force it succeeds and bumps the version.
        v2 = self.svc.generate_bracket(ms["id"], "single_elim", "ranking", force=True)
        self.assertEqual(v2["version"], 2)

    def test_record_result_advances(self):
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=1)
        ms = next(d for d in self.svc.divisions() if d["event"] == "MS")
        view = self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        # Find a ready first-round match and record a result.
        first_round = view["rounds"][0]["matches"]
        ready = next(m for m in first_round if m["ready"] and not m["winner"])
        after = self.svc.record_result(ms["id"], ready["id"], [[21, 10], [21, 12]])
        done = next(m for m in after["rounds"][0]["matches"] if m["id"] == ready["id"])
        self.assertIsNotNone(done["winner"])

    def test_build_divisions_blocked_by_finalized(self):
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=1)
        ms = next(d for d in self.svc.divisions() if d["event"] == "MS")
        self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        self.svc.finalize(ms["id"])
        with self.assertRaises(Conflict):
            self.svc.build_divisions(rng_seed=2)

    def test_override_persists_and_promotes_stub(self):
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        stub = next(p for p in self.svc.t.players.values() if p.is_stub)
        self.svc.override(f"player:{stub.id}", "gender", "M")
        self.svc.override(f"player:{stub.id}", "skill", "6")
        self.assertFalse(self.svc.t.players[stub.id].is_stub)
        # Audit log written.
        self.assertGreaterEqual(len(self.svc.repo.read_audit()), 2)

    def test_public_snapshot(self):
        self.svc.import_preview("file", FIXTURE, "auto")
        self.svc.import_commit()
        self.svc.build_divisions(rng_seed=1)
        ms = next(d for d in self.svc.divisions() if d["event"] == "MS")
        self.svc.generate_bracket(ms["id"], "single_elim", "ranking")
        snap = self.svc.public_snapshot()
        self.assertTrue(any(d["division"]["event"] == "MS" for d in snap["divisions"]))


if __name__ == "__main__":
    unittest.main()


class TestPreviewState(unittest.TestCase):
    """The page must be able to tell that an import preview is still waiting,
    otherwise a reload leaves Commit import greyed out with a preview pending."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.svc = TournamentService(
            Repository(os.path.join(self.dir.name, "t.json")))

    def tearDown(self):
        self.dir.cleanup()

    def test_has_preview_follows_preview_and_commit(self):
        self.assertFalse(self.svc.has_preview())
        self.svc.import_preview("file", FIXTURE, "auto")
        self.assertTrue(self.svc.has_preview())
        self.svc.import_commit()
        self.assertFalse(self.svc.has_preview())

    def test_players_endpoint_reports_the_pending_preview(self):
        httpd, _port = make_server(os.path.join(self.dir.name, "api.json"), port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.2)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(path, obj):
            req = urllib.request.Request(
                base + path, data=json.dumps(obj).encode(),
                headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=20))

        def get(path):
            return json.load(urllib.request.urlopen(base + path, timeout=10))
        try:
            self.assertFalse(get("/api/players")["preview"])
            post("/api/import", {"source": "file", "ref": FIXTURE})
            pending = get("/api/players")
            self.assertTrue(pending["preview"])
            self.assertGreater(len(pending["players"]), 15)   # the preview roster
            post("/api/import/commit", {})
            done = get("/api/players")
            self.assertFalse(done["preview"])
            self.assertGreater(len(done["players"]), 15)      # now committed
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestThinDivisions(unittest.TestCase):
    """One entry in a division used to "generate" an empty bracket: the page
    reported success and then showed nothing. It must say why instead."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.svc = TournamentService(
            Repository(os.path.join(self.dir.name, "t.json")))
        t = self.svc.t
        for pid, first, last in (("a", "Amy", "Nguyen"), ("b", "Bea", "Beta"),
                                 ("c", "Cal", "Gamma"), ("d", "Dee", "Delta")):
            t.players[pid] = Player(id=pid, first=first, last=last, gender="F",
                                    skill=6, events=["WD"])
        t.pairs["p1"] = Pair(id="p1", player_ids=["a", "b"], event="WD")
        t.divisions["wd"] = Division(id="wd", event="WD", label="Women's Doubles",
                                     entry_refs=[EntryRef("pair", "p1")])

    def tearDown(self):
        self.dir.cleanup()

    def test_a_one_entry_division_explains_itself(self):
        with self.assertRaises(Conflict) as caught:
            self.svc.generate_bracket("wd", "single_elim", "ranking")

        msg = str(caught.exception)
        self.assertIn("Women's Doubles has 1 entry", msg)
        self.assertIn("at least 2", msg)
        self.assertNotIn("bracket", self.svc.t.brackets)   # nothing drawn

    def test_it_generates_as_soon_as_there_are_two_entries(self):
        self.svc.t.pairs["p2"] = Pair(id="p2", player_ids=["c", "d"], event="WD")
        self.svc.t.divisions["wd"].entry_refs.append(EntryRef("pair", "p2"))

        view = self.svc.generate_bracket("wd", "single_elim", "ranking")

        matches = [m for r in view["rounds"] for m in r["matches"]]
        self.assertGreater(len(matches), 0)
        self.assertIn("wd", self.svc.t.brackets)
