"""Card gate + charter (the Three Locks) tests, run against the engine itself.

Replays Week 9, where the engine's own card put MRSH +10.5 at Pick 1 (lost 49-13).
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import beerpool as bp

ROOT = Path(__file__).parent
RUN = ROOT / "runs" / "2026-11-07_0948" / "board.json"
NOW = "2026-11-07T09:48"
SENT = "Ronnie - Week 9\n1. 37 MRSH +10.5\n2. 55 MICH -12.5\n3. 63 WYO +6.5\n4. 61 UTEP +9.5\n5. 58 NMSU +17.5\n"


def not_found(g):
    return any("is not a side on the board" in p for p in g.problems)


@unittest.skipUnless(RUN.exists(), "week 9 run not present")
class Week9Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = json.loads(RUN.read_text())
        cls.cfg = bp.Config.production()
        cls.cands, _ = bp.build_candidates(cls.board, datetime.fromisoformat(NOW), [], cls.cfg)
        cls.card, _, _ = bp.build_card(cls.cands, cfg=cls.cfg)
        cls.block = bp.submission_block("Week 9", cls.card)

    def gate(self, text):
        return bp.gate_card(text, self.cands, self.board, self.cfg)

    def test_sent_card_fails_on_marshall(self):
        g = self.gate(SENT)
        self.assertFalse(g.passed)
        self.assertTrue(any("MRSH" in p and "dog +10.5" in p for p in g.problems), g.problems)

    def test_engine_card_obeys_charter(self):
        self.assertEqual(len(self.card), 5)
        for c in self.card[:2]:
            self.assertEqual(bp.five_bans(c, self.cfg), [])
        self.assertGreaterEqual(self.card[0].p, self.card[1].p)
        self.assertTrue(self.gate(self.block).passed, self.gate(self.block).problems)
        self.assertNotIn(37, [c.game for c in self.card[:2]])

    def test_legacy_config_unchanged(self):  # the charter is off unless asked for
        legacy = bp.Config.legacy()
        cands, _ = bp.build_candidates(self.board, datetime.fromisoformat(NOW), [], legacy)
        g = bp.gate_card(SENT, cands, self.board, legacy)
        self.assertFalse(any("dog +" in p for p in g.problems))

    def test_report_shows_gate_and_withholds_nothing_when_passing(self):
        gates = []
        text = bp.report(self.board, datetime.fromisoformat(NOW), None, self.cfg, gates)
        self.assertTrue(gates[0].passed)
        self.assertIn("== GATE ==", text)
        self.assertIn("SUBMISSION (gate passed)", text)

    def test_spelled_out_names_and_totals(self):
        ok = self.gate(self.block.replace("63 WYO", "63 WYOMING").replace("55 MICH", "55 MICHIGAN"))
        self.assertTrue(ok.passed, ok.problems)
        g = self.gate("1. 48 UK/TENN UNDER 49.5\n")
        self.assertFalse(not_found(g), g.problems)

    def test_wrong_team_or_missing_line_fails(self):
        for bad in ("55 MSU -12.5", "55 MICH", "55 MICHIGAN STATE -12.5", "55 MICH -14.5"):
            g = self.gate(self.block.replace("55 MICH -12.5", bad))
            self.assertFalse(g.passed, bad)
            self.assertTrue(not_found(g), (bad, g.problems))

    def test_slot_numbering(self):
        lines = self.block.splitlines()
        all3 = "\n".join([lines[0]] + [re.sub(r"^\d\.", "3.", l) for l in lines[1:]])
        cases = {"all-3": all3, "dup": self.block.replace("2. ", "1. ", 1),
                 "missing": "\n".join(lines[:-1]), "6": self.block.replace("5. ", "6. ", 1)}
        for name, txt in cases.items():
            g = self.gate(txt)
            self.assertFalse(g.passed, name)
            self.assertTrue(any("slots must be" in p for p in g.problems), (name, g.problems))

    def test_cli_check_exit_codes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(SENT)
        r = subprocess.run([sys.executable, "beerpool.py", str(RUN), "--now", NOW, "--check", f.name],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("GATE: FAIL", r.stdout)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(self.block)
        r = subprocess.run([sys.executable, "beerpool.py", str(RUN), "--now", NOW, "--check", f.name],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


def _c(game, side, p, line=3.0, **kw):
    return bp.Candidate(game=game, league="CFB", side=side, label=f"{side} {line:+g}",
                        sheet_line=line, market_line=line - 1.5, p_market=p, **kw)


class Synthetic(unittest.TestCase):
    CFG = bp.Config.production().with_(five_min_edge=None, calibration=None)

    def test_thin_board_still_gets_five_labelled(self):
        # A blank card scores 0; a thin board gets the best five and a loud THIN label.
        cands = [_c(i, f"T{i}", p) for i, p in enumerate((0.60, 0.59, 0.53, 0.51, 0.50), 1)]
        card, thin, _ = bp.build_card(cands, cfg=self.CFG)
        self.assertEqual(len(card), 5)
        self.assertTrue(thin)
        g = bp.gate_card(bp.submission_block("X", card), cands, None, self.CFG)
        self.assertTrue(g.passed, g.problems)
        self.assertTrue(g.warnings)
        self.assertIn("THIN BOARD", g.lines()[0])

    def test_banned_five_is_hard_fail_when_alternative_exists(self):
        cands = [_c(1, "A", 0.60, line=12.0), _c(2, "B", 0.59), _c(3, "C", 0.58),
                 _c(4, "D", 0.57), _c(5, "E", 0.56), _c(6, "F", 0.555)]
        txt = "\n".join(f"{i}. {c.game} {c.label}" for i, c in enumerate(cands[:5], 1))
        g = bp.gate_card(txt, cands, None, self.CFG)
        self.assertFalse(g.passed)
        card, _, _ = bp.build_card(cands, cfg=self.CFG)
        self.assertNotIn(1, [c.game for c in card[:2]])
        self.assertTrue(bp.gate_card(bp.submission_block("X", card), cands, None, self.CFG).passed)

    def test_report_withholds_submission_when_no_card(self):
        board = {"week": "Week X", "games": []}
        text = bp.report(board, None, None, self.CFG, [])
        self.assertIn("DO NOT SEND", text)
        self.assertNotIn("SUBMISSION (gate passed)", text)

    def test_shared_thesis_and_same_env_fail(self):
        cands = [_c(1, "A", 0.60, env="x", thesis="t"), _c(2, "B", 0.59, env="x", thesis="t"),
                 _c(3, "C", 0.58), _c(4, "D", 0.57), _c(5, "E", 0.56)]
        text = "\n".join(f"{i}. {c.game} {c.label}" for i, c in enumerate(cands, 1))
        g = bp.gate_card(text, cands, None, self.CFG)
        self.assertFalse(g.passed)
        self.assertTrue(any("thesis" in p for p in g.problems), g.problems)
        self.assertTrue(any("same environment" in p for p in g.problems), g.problems)


class Bans(unittest.TestCase):
    CFG = bp.Config.production()

    def mk(self, **kw):
        base = dict(game=1, league="CFB", side="X", label="X +3", sheet_line=3.0,
                    market_line=2.0, p_market=0.56)
        base.update(kw)
        return bp.Candidate(**base)

    def test_big_dog(self):
        self.assertTrue(bp.five_bans(self.mk(sheet_line=10.0), self.CFG))
        self.assertFalse(bp.five_bans(self.mk(sheet_line=9.5), self.CFG))

    def test_low_p(self):
        self.assertTrue(bp.five_bans(self.mk(p_market=0.535), self.CFG))

    def test_unverified_move(self):
        self.assertTrue(bp.five_bans(self.mk(tags={"big_move"}), self.CFG))

    def test_totals_are_not_dogs(self):
        self.assertFalse(bp.five_bans(self.mk(side="UNDER", label="A/B UNDER 48.5", sheet_line=48.5), self.CFG))

    def test_off_in_legacy(self):
        self.assertFalse(bp.five_bans(self.mk(sheet_line=12.0, p_market=0.53), bp.Config.legacy()))


if __name__ == "__main__":
    unittest.main()
