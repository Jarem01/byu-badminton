"""Static export of the public display (what GitHub Pages serves)."""

import json
import os
import tempfile
import unittest

from tournament.model.entities import Division, EntryRef, Player, Tournament
from tournament.server import static_export
from tournament.server.service import TournamentService
from tournament.store.repository import Repository


def _saved_tournament(tmp: str) -> str:
    t = Tournament(name="Pages Cup", date="2026-03-21")
    for pid in ("p1", "p2", "p3", "p4"):
        t.players[pid] = Player(id=pid, first=pid.upper(), last="Player",
                                gender="M", skill=5, events=["MS"])
    t.divisions["div-ms"] = Division(
        id="div-ms", event="MS", label="Men's Singles",
        entry_refs=[EntryRef("player", p) for p in t.players])
    path = os.path.join(tmp, "tournament.json")
    Repository(path).save(t)
    TournamentService(Repository(path)).generate_bracket(
        "div-ms", "single_elim", method="ranking")
    return path


class TestStaticExport(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.data = _saved_tournament(self.d.name)
        self.out = os.path.join(self.d.name, "site")

    def tearDown(self):
        self.d.cleanup()

    def export(self, **kw):
        return static_export.export_static(self.data, self.out,
                                           generated="2026-11-14 00:00 UTC", **kw)

    def test_writes_the_public_page_and_assets(self):
        self.export()
        for rel in ("index.html", "static-data.json", ".nojekyll",
                    "js/public.js", "js/api.js", "js/bracket.js",
                    "css/app.css", os.path.join("assets", "logo.png")):
            self.assertTrue(os.path.isfile(os.path.join(self.out, rel)), rel)
        # The admin page needs the local server, so it is not published.
        self.assertFalse(os.path.exists(os.path.join(self.out, "admin.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "js", "admin.js")))

    def test_snapshot_matches_the_live_api_payloads(self):
        info = self.export()
        with open(os.path.join(self.out, "static-data.json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(info["divisions"], 1)
        self.assertEqual(payload["name"], "Pages Cup")
        self.assertEqual(payload["generated"], "2026-11-14 00:00 UTC")
        div = payload["public"]["divisions"][0]
        self.assertEqual(div["division"]["label"], "Men's Singles")
        self.assertTrue(div["exists"])
        self.assertTrue(any(r["matches"] for r in div["rounds"]))
        self.assertIn("blocks", payload["schedule"])
        # Nothing that only the admin should see (emails, skill, notes).
        self.assertNotIn("@", json.dumps(payload["public"]))

    def test_export_is_repeatable(self):
        path = os.path.join(self.out, "static-data.json")
        self.export()
        with open(path, "rb") as fh:
            first = fh.read()
        self.export()
        with open(path, "rb") as fh:
            self.assertEqual(first, fh.read())

    def test_repeat_export_without_changes_keeps_its_timestamp(self):
        first = static_export.export_static(self.data, self.out)
        with open(os.path.join(self.out, "static-data.json"), "rb") as fh:
            before = fh.read()
        second = static_export.export_static(self.data, self.out)
        with open(os.path.join(self.out, "static-data.json"), "rb") as fh:
            self.assertEqual(before, fh.read())
        self.assertEqual(first["generated"], second["generated"])

    def test_changed_content_gets_a_fresh_timestamp(self):
        static_export.export_static(self.data, self.out)
        svc = TournamentService(Repository(self.data))
        svc.set_format("div-ms", "round_robin")
        svc.generate_bracket("div-ms", "round_robin")
        after = static_export.export_static(self.data, self.out)
        with open(os.path.join(self.out, "static-data.json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["generated"], after["generated"])
        self.assertEqual(
            payload["public"]["divisions"][0]["division"]["format"], "round_robin")

    def test_page_is_marked_as_a_snapshot(self):
        self.export()
        with open(os.path.join(self.out, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('name="data-source" content="static"', html)
        self.assertNotIn('content="live"', html)
        with open(os.path.join(self.out, "js", "public.js"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("static-data.json", page)
        self.assertIn("snapshotOnly", page)


if __name__ == "__main__":
    unittest.main()
