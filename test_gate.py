"""Gate check on the final card (docs/LESSONS_2026_WK09.md). Flags only; nothing auto-changes."""
import unittest

import beerpool as bp
import gate


def cand(game, label, side, sheet, mkt, p, tags=()):
    return bp.Candidate(game, "CFB", side, label, sheet, mkt, p, tags=set(tags))


# A Week-9-shaped card: Pick 1 a double-digit dog, Pick 2 a number-only favorite.
MRSH = cand(37, "MRSH +10.5", "MRSH", 10.5, 7.5, 0.600)
MICH = cand(55, "MICH -12.5", "MICH", -12.5, -14.5, 0.595)
WYO = cand(63, "WYO +6.5", "WYO", 6.5, 4.5, 0.587, ["football_case"])
UTEP = cand(61, "UTEP +9.5", "UTEP", 9.5, 7.5, 0.584)
NMSU = cand(58, "NMSU +17.5", "NMSU", 17.5, 15.5, 0.575)
TENN = cand(48, "TENN -5.5", "TENN", -5.5, -6.5, 0.545, ["football_case"])
UK = cand(48, "UK +5.5", "UK", 5.5, 6.5, 0.455)
CARD = [MRSH, MICH, WYO, UTEP, NMSU]
CANDS = CARD + [TENN, UK]


def flags(lines, code):
    return [l for l in lines if l.startswith(f"FLAG {code}")]


class Gate(unittest.TestCase):
    def test_week9_card_is_flagged(self):
        out = gate.check(CARD, CANDS)
        self.assertEqual(len(flags(out, "G2")), 1)                 # MRSH +10.5 in a 5-pt slot
        self.assertIn("37 MRSH", flags(out, "G2")[0])
        self.assertEqual(len(flags(out, "G3")), 2)                 # MRSH and NMSU unverified
        self.assertEqual(len(flags(out, "R5")), 2)                 # both 5-pointers lack a case
        self.assertTrue(any(l.startswith("PASS G1") for l in out))

    def test_bottom30_offense_dog_is_a_replace_flag(self):
        bad = cand(58, "NMSU +17.5", "NMSU", 17.5, 15.5, 0.575, ["bottom30_offense"])
        out = gate.check([WYO, TENN, UTEP, bad, MICH], [WYO, TENN, UTEP, bad, MICH])
        self.assertIn("replace it", flags(out, "G3")[0])
        ok = cand(58, "NMSU +17.5", "NMSU", 17.5, 15.5, 0.575, ["offense_ok"])
        self.assertEqual(flags(gate.check([WYO, TENN, UTEP, ok, MICH], [WYO, TENN, UTEP, ok, MICH]), "G3"), [])

    def test_pick1_must_be_the_boards_best(self):
        out = gate.check([WYO, MRSH, UTEP, NMSU, MICH], CANDS)
        g1 = flags(out, "G1")
        self.assertEqual(len(g1), 1)
        self.assertIn("37 MRSH +10.5 (60.0%)", g1[0])
        self.assertIn("Cost ~0.07 pts EV", g1[0])

    def test_probability_floor(self):
        low = cand(70, "MIA +6.5", "MIA", 6.5, 6.5, 0.505, ["football_case"])
        out = gate.check([WYO, TENN, UTEP, low, MICH], [WYO, TENN, UTEP, low, MICH])
        self.assertEqual(len(flags(out, "G4")), 1)
        self.assertIn("MIA +6.5", flags(out, "G4")[0])

    def test_pdf_mismatch_flagged(self):
        out = gate.check(CARD, CANDS, pdf_lines=["OK  37 MRSH +10.5 <- sheet: ...",
                                                  "??  55 MICH -12.5 <- sheet: NOT FOUND"])
        self.assertEqual(len(flags(out, "G5")), 1)
        self.assertTrue(any(l.startswith("PASS G5") for l in gate.check(CARD, CANDS, pdf_lines=["OK x"])))

    def test_leader_swing_and_tie_break(self):
        notes = {"leader_picks": ["48 UK +5.5", "63 WYO +6.5"]}
        out = gate.check(CARD, CANDS, notes)
        self.assertTrue(any("swing vs leader: 48 TENN -5.5" in l for l in out))
        self.assertTrue(any(l.startswith("INFO leader overlap: 1 of 5") for l in out))
        # WYO matches the leader and UTEP (58.4%) is within 1% -- but UTEP is on our card already,
        # so the alternative must come from off the card.
        alt = cand(77, "CHI -6", "CHI", -6, -6, 0.582)
        out = gate.check(CARD, CANDS + [alt], notes)
        r4 = flags(out, "R4")
        self.assertEqual(len(r4), 1)
        self.assertIn("63 WYO +6.5 matches the leader; 77 CHI -6", r4[0])

    def test_clean_card_passes(self):
        good1 = cand(10, "AAA -3.5", "AAA", -3.5, -5.5, 0.62, ["football_case"])
        good2 = cand(11, "BBB +3.5", "BBB", 3.5, 1.5, 0.60, ["football_case"])
        out = gate.check([good1, good2, WYO, UTEP, TENN], [good1, good2, WYO, UTEP, TENN])
        self.assertEqual([l for l in out if l.startswith("FLAG")], [])
        self.assertIn("all checks pass", gate.section([good1, good2, WYO, UTEP, TENN],
                                                     [good1, good2, WYO, UTEP, TENN]))


if __name__ == "__main__":
    unittest.main()
