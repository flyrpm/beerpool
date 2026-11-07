import copy
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from backtest import evaluation as ev
from backtest import predictions_ledger as pl
import test_predictions_ledger as fixtures


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Ledger()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        with patch.object(ev, 'git', side_effect=lambda *a: '' if a[0] == 'status' else 'a' * 40):
            self.baseline = ev.create_baseline('ronnie-v1')
        self.baseline['payload']['frozen_model'] = copy.deepcopy(self.fixture.cfg)
        self.baseline['payload']['created_utc'] = '2026-11-07T15:00:00Z'
        self.baseline['sha256'] = pl.digest(self.baseline['payload'])
        self.ledger = self.fixture.root / 'ledger'
        self.ledger.mkdir()
        self.clock = datetime(2026, 11, 9, tzinfo=timezone.utc)

    def entry(self, week='9', historical=False, other_baseline=False):
        e = self.fixture.entry(historical=historical)
        e['payload']['week'] = week
        e['payload']['baseline_sha256'] = 'different' if other_baseline else self.baseline['sha256']
        e['sha256'] = pl.digest(e['payload'])
        pl.write_new(self.ledger / f'2026-wk{week}.json', e)
        return e

    def results(self, week='9'):
        rows = self.fixture.results()
        for r in rows:
            r['week'] = week
            r['verification'] = dict(source_url='https://www.espn.com/college-football/game/_/gameId/test',
                                     event_id='test-' + str(r['game']), checked_utc='2026-11-08T23:00:00Z')
        return rows

    def report(self, results=None, weeks=None):
        with patch.object(pl, 'now_utc', return_value=self.clock):
            return ev.report(self.baseline, self.ledger, results or [], 2026, weeks)

    def test_baseline_contains_pinned_policies_and_hashes(self):
        ev.verify_baseline(self.baseline)
        p = self.baseline['payload']
        self.assertEqual(len(p['git_commit']), 40)
        self.assertEqual(p['snapshot_policy']['max_age_hours'], 24)
        self.assertEqual(p['pool_rules']['slot_points'], [5, 5, 3, 3, 3])
        self.assertEqual(p['pool_rules']['push'], 'loss')
        self.assertEqual(p['benchmark_config']['total_shrink'], 1)
        p['snapshot_policy']['max_age_hours'] = 48
        with self.assertRaisesRegex(ValueError, 'integrity'):
            ev.verify_baseline(self.baseline)

    def test_baseline_rejects_dirty_checkout_and_source_changes(self):
        with patch.object(ev, 'git', return_value=' M beerpool.py'):
            with self.assertRaisesRegex(ValueError, 'commit all'):
                ev.create_baseline('bad')
        with patch.object(ev, 'source_hashes', return_value={}):
            with self.assertRaisesRegex(ValueError, 'source mismatch'):
                ev.verify_baseline(self.baseline, check_sources=True)

    def test_pinned_git_revision_verified_against_source_bytes(self):
        with patch.object(ev.subprocess, 'check_output', side_effect=lambda args: (ev.ROOT / args[-1].split(':', 1)[1]).read_bytes()):
            ev.verify_baseline(self.baseline, check_sources=True)
        with patch.object(ev.subprocess, 'check_output', return_value=b'changed'):
            with self.assertRaisesRegex(ValueError, 'Git revision'):
                ev.verify_baseline(self.baseline, check_sources=True)

    def test_record_enforces_deadline_policy_and_attaches_baseline(self):
        with patch.object(ev, 'verify_baseline'), patch.object(pl, 'now_utc', return_value=self.fixture.clock):
            e = ev.record(self.baseline, self.fixture.board, self.fixture.root, '2026-11-07T12:00', 2026, '9')
            pl.verify(e)
            self.assertEqual(e['payload']['baseline_sha256'], self.baseline['sha256'])
            with self.assertRaisesRegex(ValueError, 'original board'):
                ev.record(self.baseline, self.fixture.board, self.fixture.root, '2026-11-07T13:00', 2026, '9')

    def test_missing_week_and_pending_results_not_counted(self):
        self.entry()
        r = self.report(weeks=['9', '10'])
        self.assertEqual(r['cumulative']['paired_weeks'], 0)
        self.assertEqual(r['weeks'][1]['status'], 'not_recorded')
        self.assertIsNone(r['weeks'][0]['graded']['ronnie_minus_market_points'])
        text = ev.markdown(r)
        self.assertIn('pending', text)
        self.assertIn('No frozen prediction record', text)

    def test_cumulative_excludes_historical_different_and_partial_weeks(self):
        self.entry('9')
        self.entry('10', historical=True)
        self.entry('11', other_baseline=True)
        self.entry('12')
        results = self.results('9') + self.results('10') + self.results('11') + self.results('12')[:2]
        r = self.report(results)
        self.assertEqual(r['cumulative']['paired_weeks'], 1)
        self.assertEqual(r['cumulative']['ronnie_points'], 19)
        self.assertEqual(r['cumulative']['market_only_points'], 19)
        self.assertEqual(r['cumulative']['differential'], 0)
        self.assertFalse(r['weeks'][1]['eligible_for_cumulative'])

    def test_verified_finals_required(self):
        self.entry()
        with self.assertRaisesRegex(ValueError, 'source_url'):
            self.report(self.fixture.results())
        rows = self.results()
        rows[0]['verification']['checked_utc'] = '2027-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'verification time'):
            self.report(rows)

    def test_reports_reproducible_and_entry_immutable(self):
        e = self.entry()
        original = copy.deepcopy(e)
        first = self.report(self.results())
        self.assertEqual(first, self.report(self.results()))
        self.assertEqual(ev.markdown(first), ev.markdown(first))
        self.assertEqual(e, original)
        self.assertIn('H1', ev.markdown(first))
        self.assertIn('coverage_details', first['weeks'][0])


if __name__ == '__main__':
    unittest.main()
