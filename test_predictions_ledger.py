import copy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import beerpool as bp
from backtest import predictions_ledger as pl
from backtest import snapshot_replay as sr
import snapshots
import vi_parse


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = datetime(2026, 11, 7, 16, 30, tzinfo=timezone.utc)
        self.cfg = sr.freeze(bp.Config.production())
        self.cfg['created_utc'] = '2026-11-07T15:00:00Z'
        self.board = {'week': '9', 'default_lock': '2026-11-07T12:00', 'games': []}
        rows = []
        for i in range(1, 6):
            self.board['games'].append(dict(num=i, league='CFB', home=f'H{i}', away=f'A{i}',
                away_name=f'Away {i}', home_name=f'Home {i}', kickoff='2026-11-08T13:00',
                sheet_fav=f'H{i}', sheet_spread=2.5, sheet_total=45.5))
            for rot, team, line in [(i * 2 + 99, f'Away {i}', 4.5),
                                     (i * 2 + 100, f'Home {i}', -4.5)]:
                rows.append(dict(market='spread', rot=rot, team=team,
                                 cells=[{'line': line, 'price': -110}] * 10))
        self.snap = dict(taken_utc='2026-11-07T16:00:00Z', received_utc='2026-11-07T16:00:01Z',
                         league='CFB', books=vi_parse.BOOKS, rows=rows)
        self.write_snapshot()

    def write_snapshot(self):
        with gzip.open(self.root / 'snapshot.json.gz', 'wt') as f:
            json.dump(self.snap, f)

    def entry(self, **kw):
        with patch.object(pl, 'now_utc', return_value=self.clock):
            return pl.record(self.board, self.cfg, self.root, '2026-11-07T12:00',
                             2026, '9', 24, **kw)

    def results(self):
        return [dict(season=2026, week='9', game=i, league='CFB', home=f'H{i}', away=f'A{i}',
                     kickoff='2026-11-08T13:00', completed_utc='2026-11-08T22:00:00Z',
                     status='final', home_score=24, away_score=20) for i in range(1, 6)]

    def grade(self, entry, results):
        with patch.object(pl, 'now_utc', return_value=datetime(2026, 11, 9, tzinfo=timezone.utc)):
            return pl.grade(entry, results)

    def test_frozen_predictions_and_market_only_benchmark(self):
        entry = self.entry()
        payload = entry['payload']
        self.assertEqual(payload['mode'], 'prospective')
        ronnie, market = [payload['variants'][k] for k in ('ronnie', 'market_only')]
        self.assertEqual(len(ronnie['card']), 5)
        self.assertEqual({(c['game'], c['side']) for c in ronnie['candidates']},
                         {(c['game'], c['side']) for c in market['candidates']})
        self.assertNotEqual(ronnie['candidates'][0]['probability'], market['candidates'][0]['probability'])
        self.assertIsNone(market['frozen_model']['config']['calibration'])
        self.assertEqual(market['frozen_model']['config']['total_shrink'], 1)
        original = copy.deepcopy(entry)
        self.cfg['config']['calibration'].clear()
        pl.verify(entry)
        report = self.grade(entry, self.results())
        self.assertEqual(entry, original)
        for variant in report['variants'].values():
            self.assertEqual(variant['card_metrics']['earned_points'], 19)
            self.assertEqual(variant['card_metrics']['graded'], 5)
        self.assertEqual(report['ronnie_minus_market_points'], 0)

    def test_exclusive_week_entry_and_integrity(self):
        entry = self.entry()
        with patch.object(pl, 'now_utc', return_value=self.clock):
            path = pl.save_entry(self.root / 'ledger', entry)
        self.assertEqual(json.loads(path.read_text()), entry)
        with patch.object(pl, 'now_utc', return_value=self.clock):
            with self.assertRaises(FileExistsError):
                pl.save_entry(self.root / 'ledger', entry)
        entry['payload']['week'] = '10'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.grade(entry, [])

    def test_after_deadline_and_future_freeze_rejected(self):
        self.clock = datetime(2026, 11, 7, 17, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, 'before submission'):
            self.entry()
        self.clock = datetime(2026, 11, 7, 16, 30, tzinfo=timezone.utc)
        self.cfg['created_utc'] = '2026-11-07T16:31:00Z'
        with self.assertRaisesRegex(ValueError, 'future'):
            self.entry()

    def test_finished_after_deadline_rejected(self):
        late = datetime(2026, 11, 7, 17, tzinfo=timezone.utc)
        with patch.object(pl, 'now_utc', side_effect=[self.clock, late]):
            with self.assertRaisesRegex(ValueError, 'finished after'):
                pl.record(self.board, self.cfg, self.root, '2026-11-07T12:00', 2026, '9', 24)

    def test_legacy_receipt_rejected_and_historical_explicit(self):
        del self.snap['received_utc']
        self.write_snapshot()
        with self.assertRaisesRegex(ValueError, 'receipt timestamps'):
            self.entry()
        self.assertEqual(self.entry(historical=True)['payload']['mode'], 'historical')

    def test_missing_results_pending_and_partial_not_comparable(self):
        entry = self.entry()
        r = self.grade(entry, [])
        m = r['variants']['ronnie']['card_metrics']
        self.assertEqual(m['pending'], 5)
        self.assertIsNone(m['brier'])
        self.assertIsNone(r['ronnie_minus_market_points'])
        r = self.grade(entry, self.results()[:2])
        self.assertEqual(r['variants']['ronnie']['card_metrics']['graded'], 2)
        self.assertIsNone(r['ronnie_minus_market_points'])

    def test_result_identity_duplicates_invalid_scores_and_future_finals(self):
        entry = self.entry()
        for key, value in [('home', 'WRONG'), ('home_score', -1), ('away_score', 3.5),
                           ('completed_utc', '2027-01-01T00:00:00Z')]:
            rs = self.results()
            rs[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.grade(entry, rs)
        rs = self.results()
        with self.assertRaisesRegex(ValueError, 'duplicate result'):
            self.grade(entry, rs + [rs[0]])

    def test_unfinished_results_not_losses_and_report_reproducible(self):
        entry = self.entry()
        rs = self.results()
        rs[0]['status'] = 'canceled'
        first = self.grade(entry, rs)
        self.assertEqual(first, self.grade(entry, rs))
        self.assertEqual(first['variants']['ronnie']['card_metrics']['pending'], 1)
        self.assertEqual(first['result_issues'][0]['reason'], 'not_final')

    def test_push_is_loss_and_totals_orientation(self):
        g = dict(home='H', away='A')
        r = dict(home_score=24, away_score=21)
        for side, line, win, push in [('H', -3, False, True), ('A', 3, False, True),
                                      ('OVER', 45, False, True), ('UNDER', 45, False, True),
                                      ('OVER', 44.5, True, False), ('UNDER', 45.5, True, False),
                                      ('A', 3.5, True, False), ('H', -3.5, False, False)]:
            with self.subTest(side=side, line=line):
                self.assertEqual(pl.grade_pick({'side': side, 'sheet_line': line}, g, r),
                                 {'win': win, 'push': push})

    def test_duplicate_games_rejected_and_bad_age_limit(self):
        self.board['games'].append(self.board['games'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate game'):
            self.entry()
        with self.assertRaisesRegex(ValueError, 'age limit'):
            pl.record(self.board, self.cfg, self.root, '2027-11-07T12:00', 2026, '9', float('nan'))

    def test_snapshot_capture_records_receipt_time(self):
        with patch.object(snapshots, 'SNAP_DIR', str(self.root / 'capture')), \
             patch.object(snapshots, 'fetch', return_value='html'), \
             patch.object(snapshots.vi_parse, 'parse', return_value={'rows': self.snap['rows']}):
            paths = snapshots.take()
        for path in paths:
            with gzip.open(path, 'rt') as f:
                data = json.load(f)
            self.assertGreaterEqual(sr.utc(data['received_utc'], True), sr.utc(data['taken_utc'], True))


if __name__ == '__main__':
    unittest.main()
