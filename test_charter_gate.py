"""Charter gate (Three Locks) tests. Replays Week 9, where the engine's own card put
MRSH +10.5 at Pick 1 (lost 49-13)."""
import json
import unittest
from datetime import datetime
from pathlib import Path

import beerpool as bp
import charter_gate as cg

RUN = Path(__file__).parent / "runs" / "2026-11-07_0948" / "board.json"
NOW = datetime.fromisoformat("2026-11-07T09:48")
SENT = "Ronnie - Week 9\n1. 37 MRSH +10.5\n2. 55 MICH -12.5\n3. 63 WYO +6.5\n4. 61 UTEP +9.5\n5. 58 NMSU +17.5\n"


@unittest.skipUnless(RUN.exists(), "week 9 run not present")
class Week9Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = json.loads(RUN.read_text())
        cls.cfg = bp.Config.production()
        cls.cands, _ = bp.build_candidates(cls.board, NOW, [], cls.cfg)

    def test_sent_card_fails_on_marshall(self):
        ok, rep = cg.check(SENT, self.cands)
        self.assertFalse(ok)
        self.assertTrue(any("MRSH" in r and "dog +10.5" in r for r in rep))

    def test_gated_card_passes_and_has_no_big_dog_five(self):
        card = cg.charter_card(self.cands, self.cfg)
        self.assertEqual(len(card), 5)
        for c in card[:2]:
            self.assertEqual(cg.five_bans(c), [])
        ok, rep = cg.check(bp.submission_block("Week 9", card), self.cands)
        self.assertTrue(ok, rep)
        self.assertGreaterEqual(card[0].p, card[1].p)

    def test_spelled_out_names_and_totals_match(self):
        txt = "1. 55 MICH -12.5\n2. 46 USA +8.5\n3. 63 WYOMING +6.5\n4. 61 UTEP +9.5\n5. 48 TENN -5.5\n"
        ok, rep = cg.check(txt, self.cands)
        self.assertFalse(any("not found" in r for r in rep), rep)

    def test_wrong_line_is_caught(self):
        ok, rep = cg.check("1. 55 MICH -14.5\n", self.cands)
        self.assertFalse(ok)
        self.assertTrue(any("not found" in r for r in rep))


class Bans(unittest.TestCase):
    def mk(self, **kw):
        base = dict(game=1, league="CFB", side="X", label="X +3", sheet_line=3.0,
                    market_line=2.0, p_market=0.56)
        base.update(kw)
        return bp.Candidate(**base)

    def test_big_dog_banned(self):
        self.assertTrue(cg.five_bans(self.mk(sheet_line=10.0)))
        self.assertFalse(cg.five_bans(self.mk(sheet_line=9.5)))

    def test_low_p_banned(self):
        self.assertTrue(cg.five_bans(self.mk(p_market=0.535)))

    def test_unverified_move_banned(self):
        self.assertTrue(cg.five_bans(self.mk(tags={"big_move"})))

    def test_totals_not_dog_banned(self):
        self.assertFalse(cg.five_bans(self.mk(side="UNDER", label="A/B UNDER 48.5", sheet_line=48.5)))


if __name__ == "__main__":
    unittest.main()
