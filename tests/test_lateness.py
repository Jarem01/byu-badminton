"""M6: late arrivals eat their own warm-up and never cascade the day."""

import unittest

from tournament.model.entities import ScheduleBlock
from tournament.schedule.lateness import apply_lateness


def block():
    return ScheduleBlock(match_id="m", court_id="c1", start_min=0,
                         warmup_min=5, play_min=30, buffer_min=5)


class TestLateness(unittest.TestCase):
    def test_on_time(self):
        o = apply_lateness(block(), 0)
        self.assertEqual(o.usable_warmup_min, 5)
        self.assertEqual(o.delay_min, 0)
        self.assertFalse(o.cascades)

    def test_late_within_warmup_cuts_warmup_only(self):
        o = apply_lateness(block(), 3)
        self.assertEqual(o.usable_warmup_min, 2)
        self.assertEqual(o.delay_min, 0)
        self.assertFalse(o.cascades)

    def test_late_equals_warmup(self):
        o = apply_lateness(block(), 5)
        self.assertEqual(o.usable_warmup_min, 0)
        self.assertEqual(o.delay_min, 0)
        self.assertFalse(o.cascades)

    def test_late_beyond_warmup_no_cascade(self):
        o = apply_lateness(block(), 12)
        self.assertEqual(o.usable_warmup_min, 0)
        self.assertEqual(o.delay_min, 7)      # 12 - 5 warm-up
        self.assertFalse(o.cascades)          # still no forced cascade


if __name__ == "__main__":
    unittest.main()
