"""Independent exhaustive oracle and regression cases for weighted card selection."""
import itertools
import json
import random
import unittest
from datetime import datetime
from pathlib import Path

import beerpool as bp

CFG = bp.Config.legacy()


def candidate(game, p, **kw):
    return bp.Candidate(game, 'NFL', str(game), str(game), 2, 0, p, **kw)


def ev(card):
    return sum((5 if i < 2 else 3) * c.p for i, c in enumerate(card))


def oracle(cs, cfg=CFG):
    best, key = [], (-1, -1, float('-inf'))
    for size in range(2, min(5, len(cs)) + 1):
        for pair in itertools.combinations(cs, 2):
            if not all(c.five_eligible for c in pair):
                continue
            if (pair[0].env or f'game{pair[0].game}') == (pair[1].env or f'game{pair[1].game}'):
                continue
            for tail in itertools.combinations([c for c in cs if all(c is not x for x in pair)], size - 2):
                card = list(pair + tail)
                if len({c.game for c in card}) != size:
                    continue
                theses = [c.thesis for c in card if c.thesis]
                if len(set(theses)) != len(theses):
                    continue
                sweet = sum(cfg.five_min_edge is not None
                            and (not cfg.five_spreads_only or c.side not in ('OVER', 'UNDER'))
                            and cfg.five_min_edge <= c.number_edge <= cfg.five_max_edge for c in pair)
                k = size, sweet, ev(card)
                if k > key:
                    best, key = card, k
    return best


class Optimizer(unittest.TestCase):
    def test_four_pick_regression(self):
        cs = [candidate(1, .65, thesis='X'), candidate(2, .64, thesis='X'),
              candidate(1, .63), candidate(3, .60), candidate(4, .59), candidate(5, .58)]
        # Reproduce the previous greedy result independently before exercising the fix.
        greedy, used_games, used_theses = [], set(), set()
        for c in sorted(cs, key=lambda c: c.p, reverse=True):
            if c.game in used_games or (c.thesis and c.thesis in used_theses):
                continue
            greedy.append(c)
            used_games.add(c.game)
            if c.thesis:
                used_theses.add(c.thesis)
        self.assertEqual(len(greedy), 4)
        self.assertAlmostEqual(ev(greedy), 9.76)
        card, _, _ = bp.build_card(cs, cfg=CFG)
        self.assertEqual(len(card), 5)
        self.assertAlmostEqual(ev(card), 11.66)
        self.assertNotIn(cs[0], card)

    def test_infeasible_and_no_eligible_pair(self):
        card, _, _ = bp.build_card([candidate(i, .6) for i in range(4)], cfg=CFG)
        self.assertEqual(len(card), 4)
        cs = [candidate(i, .6, tags={'qb_uncertain'}) for i in range(6)]
        self.assertEqual(bp.build_card(cs, cfg=CFG)[0], [])
        self.assertEqual(bp.build_card([], cfg=CFG)[0], [])

    def test_ties_are_stable(self):
        cs = [candidate(i, .6) for i in range(7)]
        self.assertEqual(bp.build_card(cs, cfg=CFG)[0], cs[:5])

    def test_duplicates_and_constraints(self):
        cs = [candidate(1, .7), candidate(1, .69), candidate(2, .68, env='rain'),
              candidate(3, .67, env='rain'), candidate(4, .66, tags={'qb_uncertain'}),
              candidate(5, .65, thesis='X'), candidate(6, .64, thesis='X')]
        card = bp.build_card(cs, cfg=CFG)[0]
        self.assertEqual(len(card), 5)
        self.assertAlmostEqual(ev(card), ev(oracle(cs)))
        self.assertTrue(all(c.five_eligible for c in card[:2]))

    def test_sweet_spot_and_fallback(self):
        cfg = CFG.with_(five_min_edge=1.5)
        cs = [candidate(i, .7 - i * .01) for i in range(6)]
        for c in cs[:4]:
            c.sheet_line = 4
        card = bp.build_card(cs, cfg=cfg)[0]
        self.assertEqual({c.game for c in card[:2]}, {4, 5})
        cs[-1].tags.add('qb_uncertain')
        self.assertAlmostEqual(ev(bp.build_card(cs, cfg=cfg)[0]), ev(oracle(cs, cfg)))

    def test_random_boards_against_exhaustive_oracle(self):
        rng = random.Random(91)
        for _ in range(60):
            cfg = CFG.with_(five_min_edge=rng.choice([None, 1.5]))
            cs = [candidate(rng.randrange(7), rng.choice([.5, .55, .6, .65]),
                            env=rng.choice([None, 'rain']), thesis=rng.choice([None, None, 'X']),
                            tags=rng.choice([set(), {'qb_uncertain'}])) for _ in range(9)]
            for c in cs:
                c.sheet_line = rng.choice([1, 2, 4])
            actual = bp.build_card(cs, cfg=cfg)[0]
            expected = oracle(cs, cfg)
            self.assertEqual(len(actual), len(expected))
            self.assertAlmostEqual(ev(actual), ev(expected))

    def test_archived_optimal_card_unchanged(self):
        """The pre-charter engine (charter off) still reproduces the archived Week 9 card.
        The charter-on production card is tested in test_card_gate."""
        root = Path(__file__).parent
        board = json.loads((root / 'runs/2026-11-07_0948/board.json').read_text())
        cfg = bp.Config.production().with_(charter=False)
        cs, _ = bp.build_candidates(board, datetime(2026, 11, 7, 9, 48), [], cfg)
        card = bp.build_card(cs, cfg=cfg)[0]
        self.assertEqual([c.game for c in card], [37, 55, 63, 61, 58])
        text = bp.report(board, datetime(2026, 11, 7, 9, 48), None, cfg)
        archived = (root / 'runs/2026-11-07_0948/card.txt').read_text().split('\n== PDF CHECK')[0]
        # Everything up to the card is byte-identical; the gate section is new.
        self.assertEqual(text.split('\n== GATE ==')[0].rstrip(),
                         archived.split('\n== SUBMISSION ==')[0].rstrip())


if __name__ == '__main__':
    unittest.main()
