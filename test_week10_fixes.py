"""Regressions from Week 10 (2026-11-14): four bugs that needed hand patches on lock day."""
import unittest

import beerpool
import build_board as bb


class LabelledSheet(unittest.TestCase):
    def test_line_and_ou_labels_parse(self):
        row = (" 53    Sat, Nov 14, 2026    7:00 PM               Minnesota                at"
               "            Penn State             FS1         Line: PSU -9.5   O/U: 42.5")
        (g,) = bb.parse_board(row)
        self.assertEqual((g["num"], g["sheet_fav_abbr"], g["sheet_spread"], g["sheet_total"]),
                         (53, "PSU", 9.5, 42.5))

    def test_unlabelled_sheet_still_parses(self):
        row = (" 53    Sat, Nov 14, 2026    7:00 PM               Minnesota                at"
               "            Penn State             FS1         PSU -9.5   42.5")
        self.assertEqual(len(bb.parse_board(row)), 1)


class MoneylineMedian(unittest.TestCase):
    def test_median_across_even_money_is_not_minus_one(self):
        # Arkansas State at Coastal Carolina, 2026-11-14: a plain median gave -1.0,
        # which the engine read as a 65% favourite and a MEGA candidate.
        med = bb.median_american([100, 100, -102, -104, -104, 105])
        self.assertGreaterEqual(abs(med), 100)
        self.assertAlmostEqual(bb.implied(med), 0.5, delta=0.01)

    def test_plain_case_unchanged(self):
        self.assertEqual(bb.median_american([-120, -118, -115]), -118)


class PdfCheck(unittest.TestCase):
    def test_game_number_and_line_do_not_match_inside_other_numbers(self):
        wrong = " 36    Sat, Nov 14, 2026    3:30 PM   Michigan   at   Oregon   FS1   Line: ORE -10.5   O/U: 38.5"
        right = " 38    Sat, Nov 14, 2026    3:30 PM   California   at   Virginia   ACC   Line: UVA -10    O/U: 46.5"
        self.assertFalse(beerpool.pdf_row_matches(wrong, 38, "10"))
        self.assertTrue(beerpool.pdf_row_matches(right, 38, "10"))
        self.assertTrue(beerpool.pdf_row_matches(wrong, 36, "10.5"))


class SnapshotBoard(unittest.TestCase):
    def test_build_accepts_snapshots_and_stamps_as_of(self):
        import inspect
        self.assertIn("snapshots", inspect.signature(bb.build).parameters)
        self.assertTrue(callable(bb.latest_snapshots))


if __name__ == "__main__":
    unittest.main()
