import unittest
from unittest.mock import patch

from backtest import certify
from backtest import predictions_ledger as pl
from backtest import research_report as rr
import test_evaluation as fixtures


class ResearchReport(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Evaluation()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def report(self, results=None, weeks=None):
        f = self.fixture
        with patch.object(pl, 'now_utc', return_value=f.clock):
            return rr.report(f.baseline, f.ledger, results or [], 2026, weeks)

    def test_rates_use_same_graded_denominator_and_fixed_descriptive_bins(self):
        picks = [dict(probability=.6, status='graded', win=True, push=False),
                 dict(probability=.5, status='graded', win=False, push=True),
                 dict(probability=.9, status='pending')]
        m = rr.summarize(picks)
        self.assertEqual(m['selected'], 3)
        self.assertEqual(m['graded'], 2)
        self.assertEqual(m['pending'], 1)
        self.assertAlmostEqual(m['predicted_win_rate'], .55)
        self.assertEqual(m['observed_win_rate'], .5)
        self.assertEqual(sum(c['n'] for c in m['calibration']), 2)
        self.assertAlmostEqual(m['brier'], (.4**2 + .5**2)/2)

    def test_expected_weeks_do_not_hide_recorded_weeks(self):
        self.fixture.entry()
        data = self.report(self.fixture.results(), ['10'])
        self.assertEqual([w['week'] for w in data['weeks']], ['9', '10'])
        self.assertEqual(data['weeks'][1]['status'], 'not_recorded')
        self.assertEqual(data['research']['fully_graded_prospective_weeks'], 1)
        self.assertEqual(data['research']['cumulative']['ronnie']['graded'], 5)
        self.assertEqual(data['cumulative']['ronnie_points'], 19)
        self.assertIn('Graded n', rr.markdown(data))

    def test_historical_and_pending_weeks_not_added_to_research_sample(self):
        self.fixture.entry('9', historical=True)
        self.fixture.entry('10')
        data = self.report(self.fixture.results('9'), ['9', '10', '11'])
        self.assertEqual(data['research']['fully_graded_prospective_weeks'], 0)
        self.assertEqual(data['research']['cumulative']['ronnie']['calibration'], [])
        self.assertIn('No graded observations', rr.markdown(data))
        self.assertIn('N/A', rr.markdown(data))
        self.assertIn('not independent trials', data['research']['warning'])

    def test_research_report_is_reproducible(self):
        self.fixture.entry()
        results = self.fixture.results()
        data = self.report(results)
        self.assertEqual(data, self.report(results))
        self.assertEqual(rr.markdown(data), rr.markdown(data))
        self.assertEqual(sum(c['n'] for c in data['research']['cumulative']['ronnie']['calibration']), 5)

    def test_duplicate_expected_weeks_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate expected weeks'):
            self.report(weeks=['10', '10'])


class OperationalRehearsal(unittest.TestCase):
    def test_synthetic_end_to_end_never_counts_as_prospective(self):
        summary = certify.run()
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['ingested_games'], 7)
        self.assertEqual(summary['picks_per_variant'], 5)
        self.assertEqual(summary['fully_graded_prospective_weeks'], 0)
        self.assertIn('SYNTHETIC', summary['label'])
        self.assertEqual(summary['temporary_artifacts'], 'deleted on completion')


if __name__ == '__main__':
    unittest.main()
