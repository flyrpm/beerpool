"""Charter gate (Three Locks) tests. Replays Week 9, where the engine's own card put
MRSH +10.5 at Pick 1 (lost 49-13)."""
import json
import re
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
        ok, rep = cg.check(SENT, self.cands, self.board)
        self.assertFalse(ok)
        self.assertTrue(any("MRSH" in r and "dog +10.5" in r for r in rep))

    def test_gated_card_passes_and_has_no_big_dog_five(self):
        card = cg.charter_card(self.cands, self.cfg)
        self.assertEqual(len(card), 5)
        for c in card[:2]:
            self.assertEqual(cg.five_bans(c), [])
        ok, rep = cg.check(bp.submission_block("Week 9", card), self.cands, self.board)
        self.assertTrue(ok, rep)
        self.assertGreaterEqual(card[0].p, card[1].p)

    def test_spelled_out_names_and_totals_match(self):
        txt = "1. 55 MICH -12.5\n2. 46 USA +8.5\n3. 63 WYOMING +6.5\n4. 61 UTEP +9.5\n5. 48 UK/TENN UNDER 49.5\n"
        ok, rep = cg.check(txt, self.cands, self.board)
        self.assertFalse(any("not found" in r for r in rep), rep)

    def _gated_block(self):
        return bp.submission_block("Week 9", cg.charter_card(self.cands, self.cfg))

    def test_wrong_team_fails(self):  # review P1: MSU -12.5 / bare MICH used to pass
        for bad in ("55 MSU -12.5", "55 MICH", "55 MICHIGAN STATE -12.5"):
            ok, rep = cg.check(self._gated_block().replace("55 MICH -12.5", bad),
                               self.cands, self.board)
            self.assertFalse(ok, bad)
            self.assertTrue(any("not found" in r for r in rep), (bad, rep))

    def test_spelled_out_full_name_passes(self):
        ok, rep = cg.check(self._gated_block().replace("63 WYO", "63 WYOMING")
                           .replace("55 MICH", "55 MICHIGAN"), self.cands, self.board)
        self.assertTrue(ok, rep)

    def test_slot_numbering(self):  # review P2
        blk = self._gated_block()
        lines = blk.splitlines()
        all3 = "\n".join([lines[0]] + [re.sub(r"^\d\.", "3.", l) for l in lines[1:]])
        dup = blk.replace("2. ", "1. ", 1)
        missing = "\n".join(lines[:-1])
        oor = blk.replace("5. ", "6. ", 1)
        for name, txt in (("all-3", all3), ("dup", dup), ("missing", missing), ("6", oor)):
            ok, rep = cg.check(txt, self.cands, self.board)
            self.assertFalse(ok, name)
            self.assertTrue(any("slots must be" in r for r in rep), (name, rep))

    def test_wrong_line_is_caught(self):
        ok, rep = cg.check("1. 55 MICH -14.5\n", self.cands)
        self.assertFalse(ok)
        self.assertTrue(any("not found" in r for r in rep))


def _c(game, side, p, line=3.0, **kw):
    return bp.Candidate(game=game, league="CFB", side=side, label=f"{side} {line:+g}",
                        sheet_line=line, market_line=line - 1.5, p_market=p, **kw)


class GenerationAndCorrelation(unittest.TestCase):
    CFG = bp.Config.production().with_(five_min_edge=None)

    def test_pick_two_competes_against_omitted_candidates(self):
        board = [_c(i, f"T{i}", p) for i, p in enumerate(
            [.61, .60, .59, .58, .57, .56], 1)]
        board[1].market_line = board[1].sheet_line  # Outside the legacy edge band.
        card = cg.charter_card(board, bp.Config.production())
        self.assertEqual([c.game for c in card[:2]], [1, 2])
        weaker = bp.submission_block("Test", [board[i] for i in (0, 2, 3, 4, 5)])
        ok, report = cg.check(weaker, board)
        self.assertFalse(ok)
        self.assertTrue(any("stronger legal" in line for line in report))

    def test_low_probability_board_is_not_sendable(self):  # review P2 (#2)
        cands = [_c(i, f"T{i}", p) for i, p in enumerate((0.60, 0.59, 0.53, 0.51, 0.50), 1)]
        ok, out = cg.final_section({"week": "Week X"}, cands, self.CFG)
        self.assertFalse(ok)
        self.assertIn("DO NOT SEND", out)
        self.assertNotIn("send THIS one", out)
        self.assertNotIn("```", out)

    def test_cli_exits_nonzero_on_fail(self):
        import subprocess, sys, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("1. 99 NOPE -1.5\n")
        r = subprocess.run([sys.executable, "charter_gate.py", str(RUN), "--now",
                            "2026-11-07T09:48", "--check", f.name], capture_output=True, text=True)
        if RUN.exists():
            self.assertNotEqual(r.returncode, 0)

    def test_shared_thesis_and_same_env_fail(self):  # review P2 (#4)
        cands = [_c(1, "A", 0.60, env="x", thesis="t"), _c(2, "B", 0.59, env="x", thesis="t"),
                 _c(3, "C", 0.58), _c(4, "D", 0.57), _c(5, "E", 0.56)]
        card = "\n".join(f"{i}. {c.game} {c.label}" for i, c in enumerate(cands, 1))
        ok, rep = cg.check(card, cands)
        self.assertFalse(ok)
        self.assertTrue(any("thesis" in r for r in rep), rep)
        self.assertTrue(any("same environment" in r for r in rep), rep)


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
