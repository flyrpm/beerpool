import json
import unittest
from datetime import datetime
from pathlib import Path

import beerpool
from beerpool import (book_range, build_candidates, build_card, calibrate_margin,
                      devig, margin_pmf, mega_gain, movement_tags, p_strict_above,
                      p_strict_below, submission_block)

# Rule tests run with the legacy settings; tuning is covered by the backtest.
LEGACY = beerpool.Config.legacy()
BOARD = json.loads((Path(__file__).parent / "board.example.json").read_text())
NOW = datetime.fromisoformat(BOARD["now"])


def run(board=BOARD, now=NOW, cfg=LEGACY):
    cands, sweep = build_candidates(board, now, [], cfg)
    card, thin, ranked = build_card(cands, cfg=cfg)
    return cands, sweep, card, thin


class Pricing(unittest.TestCase):
    def test_devig(self):
        self.assertAlmostEqual(devig(-110, -110), 0.5)
        self.assertAlmostEqual(devig(-118, -102), 0.517, places=3)

    def test_push_is_loss(self):
        mu = calibrate_margin("NFL", -3, 0.5)          # home -3, even juice
        pmf = margin_pmf(mu, "NFL")
        fav_minus3 = p_strict_above(pmf, 3)
        dog_plus3 = p_strict_below(pmf, 3)
        self.assertAlmostEqual(fav_minus3, dog_plus3, places=3)
        self.assertLess(fav_minus3 + dog_plus3, 0.95)  # ~8% push mass lost
        # -3 plays like -3.5
        self.assertAlmostEqual(fav_minus3, p_strict_above(pmf, 3.5), places=9)

    def test_mega_breakeven_is_50(self):
        self.assertAlmostEqual(mega_gain(0.5), 0.0)
        self.assertAlmostEqual(mega_gain(0.54), 0.4)
        self.assertAlmostEqual(mega_gain(0.59), 0.9)


class Rules(unittest.TestCase):
    def test_no_dallas(self):
        cands, *_ = run()
        self.assertNotIn("DAL", {c.side for c in cands})

    def test_friday_game_locked(self):
        cands, sweep, *_ = run()
        self.assertNotIn(12, {c.game for c in cands})

    def test_book_conflict_no_call(self):
        cands, *_ = run()
        self.assertFalse([c for c in cands if c.game == 64 and c.side in ("TEN", "IND")])

    def test_uncertain_qb_not_five(self):
        _, _, card, _ = run()
        for c in card[:2]:
            self.assertTrue(c.five_eligible)
        self.assertIn(62, {c.game for c in card[2:]})

    def test_one_pick_per_game(self):
        _, _, card, _ = run()
        games = [c.game for c in card]
        self.assertEqual(len(games), len(set(games)))
        self.assertEqual(len(card), 5)

    def test_market_flip_favors_flip_side(self):
        cands, *_ = run()
        p = {c.side: c.p for c in cands if c.game == 62}
        self.assertGreater(p["BAL"], 0.5)
        self.assertLess(p["CIN"], 0.5)

    def test_under_wants_higher_number(self):
        cands, *_ = run()
        under = next(c for c in cands if c.game == 71 and c.side == "UNDER")
        self.assertEqual(under.number_edge, 2)
        self.assertGreater(under.p, 0.55)

    def test_format(self):
        _, _, card, _ = run()
        block = submission_block("Week 10", card)
        lines = block.splitlines()
        self.assertEqual(lines[0], "Ronnie - Week 10")
        self.assertRegex(lines[1], r"^1\. \d+ \S+")
        self.assertNotIn("Mega", block)
        self.assertIn("71 PIT/TB UNDER 41.5", block)
        self.assertIn("56 UTAH -6.5", block)

    def test_one_stale_book_is_not_a_conflict(self):
        self.assertEqual(book_range([8.5, 8.5, 8.5, 8.5, 8.5, 8.0, 10.5]), 0.0)
        self.assertEqual(book_range([2.5, 2.5, 3, 4, 4.5]), 1.5)

    def test_movement_tags(self):
        # NMSU: +12.5 open -> +15.5 now. Market fading NMSU (money on Liberty).
        self.assertEqual(movement_tags(15.5, 12.5, True), {"big_move", "steam_against"})
        # Wyoming: +8.5 open -> +4 now. Big move, but toward Wyoming.
        self.assertEqual(movement_tags(4.0, 8.5, True), {"big_move"})
        # UNLV: -8.5 -> -4 is the same move seen from the favourite: against UNLV.
        self.assertEqual(movement_tags(-4.0, -8.5, True), {"big_move", "steam_against"})
        # Total 47.5 -> 45.5: money on the under, against the over.
        self.assertEqual(movement_tags(45.5, 47.5, True), set())    # UNDER
        self.assertEqual(movement_tags(45.5, 47.5, False), {"steam_against"})  # OVER

    def _utah_opened_minus5(self):
        b = json.loads(json.dumps(BOARD))
        g = next(x for x in b["games"] if x["num"] == 56)
        g["market"]["open_home"] = 5.0   # BOIS home: opened UTAH -5, now UTAH -8.5
        return b, g

    def test_big_move_not_five(self):
        b, _ = self._utah_opened_minus5()
        cands, *_ = run(b)
        utah = next(c for c in cands if c.game == 56 and c.side == "UTAH")
        self.assertEqual(utah.tags, {"big_move"})      # moved toward Utah: not steam against
        self.assertFalse(utah.five_eligible)
        boise = next(c for c in cands if c.game == 56 and c.side == "BOIS")
        self.assertIn("steam_against", boise.tags)

    def test_notes_can_clear_tags(self):
        b, g = self._utah_opened_minus5()
        g["notes"]["UTAH"]["clear_tags"] = ["big_move"]   # e.g. news verified
        cands, *_ = run(b)
        utah = next(c for c in cands if c.game == 56 and c.side == "UTAH")
        self.assertTrue(utah.five_eligible)

    def test_five_point_sweet_spot_rule(self):
        cands, *_ = run()
        if True:
            card, _, _ = build_card(cands, cfg=LEGACY.with_(five_min_edge=1.5))
            self.assertEqual(len(card), 5)
            sweet = [c for c in cands if c.side not in ("OVER", "UNDER")
                     and 1.5 <= c.number_edge <= 3.0 and c.five_eligible]
            if sweet:   # the best sweet-spot spread must hold a 5-pt slot
                best = max(sweet, key=lambda c: c.p)
                self.assertIn(best.game, {c.game for c in card[:2]})
            # every 5-pointer is either sweet-spot or a fallback filling an empty slot
            for c in card[:2]:
                self.assertTrue(c.five_eligible)

    def test_calibration_by_edge_bucket(self):
        table = {"spread": {"2-3": {"rate": 0.58, "mean_p": 0.55},
                            "3.5+": {"rate": 0.51, "mean_p": 0.58}}}
        self.assertAlmostEqual(beerpool.calibrate(0.55, "spread", 2.0, table), 0.58)
        self.assertAlmostEqual(beerpool.calibrate(0.60, "spread", 4.0, table), 0.52)
        self.assertEqual(beerpool.calibrate(0.53, "total", 1.0, table), 0.53)  # no cell
        self.assertEqual(beerpool.calibrate(0.53, "spread", 2.0, None), 0.53)  # no table
        self.assertEqual(beerpool.edge_bucket(0.0), "<=0")
        self.assertEqual(beerpool.edge_bucket(-1.5), "<=0")
        self.assertEqual(beerpool.edge_bucket(1.5), "1-1.5")

    def test_configs_do_not_leak(self):
        """Building with one config must not change what another config produces."""
        a1 = [round(c.p, 6) for c in run(cfg=LEGACY)[0]]
        run(cfg=LEGACY.with_(total_shrink=0.1, huge_edge_p=0.5, big_move_caps=False))
        a2 = [round(c.p, 6) for c in run(cfg=LEGACY)[0]]
        self.assertEqual(a1, a2)

    def test_fast_pricing_matches_slow(self):
        for lg in ("NFL", "CFB"):
            for mu in (-17.3, -3.0, 0.0, 2.5, 6.8):
                pmf, cum = margin_pmf(mu, lg), beerpool.margin_cum(mu, lg)
                for x in (-7, -3.5, -3, 0, 2.5, 3, 10.5):
                    self.assertAlmostEqual(p_strict_above(pmf, x), cum.above(x), places=3)
                    self.assertAlmostEqual(p_strict_below(pmf, x), cum.below(x), places=3)

    def test_moneyline_blend_moves_small_spreads(self):
        """With ML given, the fair margin blends spread-implied and ML-implied means."""
        mu_spread = calibrate_margin("NFL", -1.5, 0.5)
        mu_ml_fav = calibrate_margin("NFL", -1.5, 0.5, p_home_ml=0.62)
        mu_ml_dog = calibrate_margin("NFL", -1.5, 0.5, p_home_ml=0.45)
        self.assertGreater(mu_ml_fav, mu_spread)
        self.assertLess(mu_ml_dog, mu_spread)

    def test_note_adj_is_clamped(self):
        b = json.loads(json.dumps(BOARD))
        g = next(x for x in b["games"] if x["num"] == 56)
        g["notes"]["UTAH"]["adj"] = 0.10
        warns = []
        cands, _ = build_candidates(b, NOW, warns, LEGACY)
        utah = next(c for c in cands if c.game == 56 and c.side == "UTAH")
        self.assertAlmostEqual(utah.adj, 0.02)
        self.assertTrue(any("clamped" in w for w in warns))

    def test_thin_board(self):
        thin_board = {"week": "W", "default_lock": "2026-11-07T12:00", "games": [
            {"num": 1, "league": "NFL", "away": "A", "home": "B",
             "sheet_fav": "B", "sheet_spread": 2.5,
             "market": {"fav": "B", "spread": 2.5}}]}
        *_, thin = run(thin_board)
        self.assertTrue(thin)


if __name__ == "__main__":
    unittest.main()
