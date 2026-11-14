"""`publish` refreshes the public snapshot and commits just that folder."""

import os
import shutil
import subprocess
import tempfile
import unittest

from tournament.model.entities import Division, EntryRef, Player, Tournament
from tournament.publish import publish_snapshot
from tournament.server.service import TournamentService
from tournament.store.repository import Repository

_HAVE_GIT = shutil.which("git") is not None


def saved_tournament(tmp: str) -> str:
    t = Tournament(name="Pages Cup", date="2026-03-21")
    for pid in ("p1", "p2", "p3", "p4"):
        t.players[pid] = Player(id=pid, first=pid.upper(), last="Player",
                                gender="M", skill=5, events=["MS"])
    t.divisions["div-ms"] = Division(
        id="div-ms", event="MS", label="Men's Singles",
        entry_refs=[EntryRef("player", p) for p in t.players])
    path = os.path.join(tmp, "tournament.json")
    Repository(path).save(t)
    TournamentService(Repository(path)).generate_bracket("div-ms", "single_elim")
    return path


def git(root: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, check=True).stdout


@unittest.skipUnless(_HAVE_GIT, "git is not installed")
class TestPublish(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = self.d.name
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "organizer@example.com")
        git(self.root, "config", "user.name", "Organizer")
        self.data = saved_tournament(self.root)
        with open(os.path.join(self.root, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("unrelated work\n")
        git(self.root, "add", "notes.txt")
        git(self.root, "commit", "-q", "-m", "start")

    def tearDown(self):
        self.d.cleanup()

    def publish(self, **kw):
        return publish_snapshot(self.data, os.path.join(self.root, "site"),
                                cwd=self.root, push=False, **kw)

    def test_commits_the_refreshed_snapshot(self):
        report = self.publish()
        self.assertTrue(report["ok"])
        self.assertTrue(report["committed"])
        self.assertFalse(report["pushed"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "site", "index.html")))
        # Only the snapshot is committed; unrelated files stay as they were.
        changed = git(self.root, "show", "--name-only", "--pretty=format:", "HEAD")
        paths = [p for p in changed.splitlines() if p.strip()]
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith("site/") for p in paths), paths)
        self.assertIn("Refresh the published snapshot", git(self.root, "log", "-1",
                                                            "--pretty=%s"))

    def test_second_publish_reports_it_is_already_current(self):
        self.publish()
        again = self.publish()
        self.assertTrue(again["ok"])
        self.assertFalse(again["committed"])
        self.assertIn("already up to date", again["detail"])

    def test_outside_a_git_checkout_the_files_are_still_written(self):
        with tempfile.TemporaryDirectory() as bare:
            report = publish_snapshot(self.data, os.path.join(bare, "site"),
                                      cwd=bare, push=False)
            self.assertFalse(report["committed"])
            self.assertIn("not a git checkout", report["detail"])
            self.assertTrue(os.path.isfile(os.path.join(bare, "site", "index.html")))


if __name__ == "__main__":
    unittest.main()
