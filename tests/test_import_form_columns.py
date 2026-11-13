"""Regressions from the real fall-2026 Google-Form export.

The form asks for the MD/WD partner and then for the XD partner under the exact
same question text, so those two columns arrive with identical headers.
``csv.DictReader`` kept only the last one, silently replacing every MD/WD
partner with the XD partner. The player's own ``Gender`` answer was ignored too.
"""

import unittest

from tournament.engine.grouping import build_divisions
from tournament.ingest.importer import build_tournament
from tournament.ingest.source_csv import read_rows_from_text
from tournament.validate.rules import check_partner_events

HEADER = (
    "Timestamp,First Name,Last Name,Email,Gender,"
    "Approximate Skill Level:,What event(s) will you be participating?,"
    "Do you already have a partner for MD/WD? (N/A if not applicable),"
    "What is your partner’s full name? (N/A if not applicable),"
    "\"If no, are you willing to be assigned a random partner?\","
    "Do you already have a partner for XD? (N/A if not applicable),"
    "What is your partner’s full name? (N/A if not applicable),"
    "\"If no, are you willing to be assigned a random partner?\""
)

CSV = HEADER + "\n" + "\n".join([
    # MD partner (Zhi-Han) and XD partner (Eugene) in the two identical columns,
    # and a mutual XD request although the event column only says MD.
    "1,Stanley,Chen,s@x.edu,Male,5,Men’s Doubles (MD),Yes,Zhi-Han Tsai,,Yes,Eugene Poh,",
    "1,Eugene,Poh,e@x.edu,Female,5,Mixed Doubles (XD),Yes,Stanley,,Yes,Yes,Stanley,",
    # Non-Latin partner name, and "No" to the random-partner question.
    "1,Kaya,Hsiao,k@x.edu,Female,8,Women’s Doubles (WD),Yes,李佳嬛,No,N/A,,",
    # Free-text answer instead of a name.
    "1,Emily,Petty,em@x.edu,Female,7,Mixed Doubles (XD),No,"
    "\"I don’t have one, am open to be assigned if there is an extra!\",Yes,No,N/A,Yes",
    # One-sided request to a player who did not enter XD.
    "1,Sonny,Middlebrook,sn@x.edu,Male,7,Mixed Doubles (XD),N/A,Kaya Hsiao,No,"
    "Yes,Kaya Hsiao,No",
]) + "\n"


class TestFall2026FormColumns(unittest.TestCase):
    def setUp(self):
        headers, rows = read_rows_from_text(CSV)
        self.headers = headers
        self.res = build_tournament(headers, rows, schema="auto")
        self.t = self.res.tournament

    def player(self, last):
        return next(p for p in self.t.players.values() if p.last == last)

    def hints(self, last):
        pid = self.player(last).id
        reg = next(r for r in self.t.registrations if r.player_id == pid)
        return [(h.raw_name, h.event_hint) for h in reg.partner_hints]

    def division(self, event):
        grouped = build_divisions(self.t, rng_seed=1)
        return grouped, next(d for d in grouped.divisions.values()
                             if d.event == event)

    def test_duplicate_headers_are_kept_apart(self):
        self.assertEqual(len(self.headers), 13)
        self.assertEqual(len(set(self.headers)), 13)

    def test_both_partner_blocks_are_read(self):
        self.assertEqual(self.hints("Chen"),
                         [("Zhi-Han Tsai", "MD"), ("Eugene Poh", "XD")])

    def test_declared_gender_beats_event_inference(self):
        self.assertEqual(self.player("Poh").gender, "F")    # XD only -> would be U
        self.assertEqual(self.player("Chen").gender, "M")

    def test_random_partner_answer_comes_from_the_right_block(self):
        self.assertFalse(self.player("Hsiao").willing_random)   # answered No
        self.assertTrue(self.player("Petty").willing_random)    # answered Yes

    def test_non_latin_partner_name_is_kept(self):
        self.assertIn(("李佳嬛", "WD"), self.hints("Hsiao"))

    def test_prose_answer_does_not_become_a_player(self):
        self.assertFalse(any("have one" in p.full.lower()
                             for p in self.t.players.values()))

    def test_mutual_cross_event_request_is_paired_and_flagged(self):
        grouped, xd = self.division("XD")
        members = {frozenset(self.t.pairs[e.ref_id].player_ids)
                   for e in xd.entry_refs}
        self.assertIn(frozenset({self.player("Poh").id, self.player("Chen").id}),
                      members)
        self.assertIn("partner_event_mismatch",
                      {i.code for i in check_partner_events(self.t)})

    def test_one_sided_request_to_unregistered_player_is_refused(self):
        grouped, xd = self.division("XD")
        sonny, kaya = self.player("Middlebrook"), self.player("Hsiao")
        members = {frozenset(self.t.pairs[e.ref_id].player_ids)
                   for e in xd.entry_refs}
        self.assertNotIn(frozenset({sonny.id, kaya.id}), members)
        self.assertIn(sonny.id, grouped.unpaired)
        self.assertIn("partner_not_entered",
                      {i.code for i in check_partner_events(self.t)})


if __name__ == "__main__":
    unittest.main()
