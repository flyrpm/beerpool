import copy
import gzip
import hashlib
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import unittest

import beerpool as bp
import vi_parse
from backtest import snapshot_replay as sr


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.cfg = sr.freeze(bp.Config.legacy())
        self.board = {'week': 'W', 'default_lock': '2026-11-07T12:00', 'games': [
            {'num': 1, 'league': 'NFL', 'away': 'DAL', 'home': 'NYG',
             'names': 'Dallas Cowboys at New York Giants', 'kickoff': '2026-11-08T13:00',
             'sheet_fav': 'NYG', 'sheet_spread': 3, 'sheet_total': 45,
             'market': {'fav': 'NYG', 'spread': 30}, 'notes': {'NYG': {'adj': .02}}}]}

    def snapshot(self, name, timestamp, spread=-4, received=None):
        rows = []
        for market in ('spread', 'total'):
            for rot, team, line in [(101, 'Dallas Cowboys', -spread if market == 'spread' else 46),
                                    (102, 'New York Giants', spread if market == 'spread' else 46)]:
                rows.append({'market': market, 'rot': rot, 'team': team,
                             'cells': [{'line': line, 'price': -110}] * 10})
        snap = dict(taken_utc=timestamp, league='NFL', books=vi_parse.BOOKS, rows=rows)
        if received:
            snap['received_utc'] = received
        with gzip.open(self.path / name, 'wt') as f:
            json.dump(snap, f)

    def run_replay(self, **kw):
        return sr.replay(self.board, self.cfg, self.path, '2026-11-07T12:00', **kw)

    def test_strict_cutoff_timezone_and_content_time_order(self):
        self.snapshot('z_old.json.gz', '2026-11-07T16:00:00Z', -4)
        self.snapshot('a_new.json.gz', '2026-11-07T11:59:00-05:00', -5)
        self.snapshot('equal.json.gz', '2026-11-07T17:00:00Z', -6)
        self.snapshot('future.json.gz', '2026-11-07T17:01:00Z', -7)
        r = self.run_replay()
        self.assertTrue(r['games'][0]['snapshot'].endswith('a_new.json.gz'))
        self.assertEqual(r['sweep'][0]['market'], 'NYG -5')
        self.assertEqual(r['decision_utc'], '2026-11-07T17:00:00+00:00')

    def test_missing_future_and_equal_never_fall_back_to_board_market(self):
        for ts in (None, '2026-11-07T17:00:00Z', '2026-11-07T18:00:00Z'):
            if ts:
                self.snapshot('only.json.gz', ts)
            r = self.run_replay()
            self.assertEqual(r['coverage']['covered_games'], 0)
            self.assertEqual(r['card'], [])
            self.assertEqual(r['games'][0]['status'], 'no_matching_pre_deadline_snapshot')

    def test_earlier_game_deadline_excludes_game(self):
        self.snapshot('x.json.gz', '2026-11-07T16:00:00Z')
        self.board['games'][0]['kickoff'] = '2026-11-07T11:00'
        r = self.run_replay()
        self.assertEqual(r['games'][0]['status'], 'locked_before_submission')
        self.assertEqual(r['games'][0]['cutoff_utc'], '2026-11-07T16:00:00+00:00')

    def test_receipt_after_cutoff_rejected(self):
        self.snapshot('x.json.gz', '2026-11-07T16:59:59Z', received='2026-11-07T17:00:01Z')
        self.assertEqual(self.run_replay()['coverage']['covered_games'], 0)

    def test_age_policy_and_legacy_receipt_warning(self):
        self.snapshot('x.json.gz', '2026-11-06T16:00:00Z')
        self.assertEqual(self.run_replay(max_age_hours=24)['coverage']['covered_games'], 0)
        r = self.run_replay()
        self.assertEqual(r['coverage']['covered_games'], 1)
        self.assertTrue(any('receipt before cutoff' in w for w in r['warnings']))

    def test_bad_snapshot_and_missing_names_are_explicit(self):
        self.snapshot('x.json.gz', '2026-11-07T16:00:00')
        self.assertEqual(len(self.run_replay()['snapshot_errors']), 1)
        del self.board['games'][0]['names']
        self.assertEqual(self.run_replay()['games'][0]['status'], 'missing_full_team_names')

    def test_partial_market_is_reported_without_backfilling(self):
        self.snapshot('old.json.gz', '2026-11-07T15:00:00Z', -4)
        self.snapshot('new.json.gz', '2026-11-07T16:00:00Z', -5)
        path = self.path / 'new.json.gz'
        with gzip.open(path, 'rt') as f:
            snap = json.load(f)
        snap['rows'] = [r for r in snap['rows'] if r['market'] == 'spread']
        with gzip.open(path, 'wt') as f:
            json.dump(snap, f)
        r = self.run_replay()
        self.assertEqual(r['games'][0]['markets'], {'spread': True, 'total': False})
        self.assertNotIn('market_total', r['sweep'][0])

    def test_other_league_and_explicit_earlier_lock(self):
        self.snapshot('x.json.gz', '2026-11-07T16:00:00Z')
        self.board['games'][0]['league'] = 'CFB'
        self.assertEqual(self.run_replay()['coverage']['covered_games'], 0)
        self.board['games'][0]['lock'] = '2026-11-07T10:00'
        self.assertEqual(self.run_replay()['games'][0]['status'], 'locked_before_submission')

    def test_config_frozen_detached_and_source_checked(self):
        cfg = bp.Config(calibration={'spread': {'2-3': {'rate': .58, 'mean_p': .55}}})
        manifest = sr.freeze(cfg)
        cfg.calibration['spread']['2-3']['rate'] = .99
        self.assertEqual(manifest['config']['calibration']['spread']['2-3']['rate'], .58)
        bad = copy.deepcopy(self.cfg)
        bad['source_sha256']['beerpool.py'] = 'different'
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            sr.replay(self.board, bad, self.path, '2026-11-07T12:00')

    def test_provenance_hash_matches_bytes_parsed_not_later_replacement(self):
        self.snapshot('x.json.gz', '2026-11-07T16:00:00Z')
        path = self.path / 'x.json.gz'
        original = path.read_bytes()
        real_market_for = sr.bb.market_for
        def replace_after_read(game, snap):
            path.write_bytes(b'replaced after ingestion')
            return real_market_for(game, snap)
        with patch.object(sr.bb, 'market_for', side_effect=replace_after_read):
            report = self.run_replay()
        self.assertEqual(report['games'][0]['snapshot_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(report['sweep'][0]['market'], 'NYG -4')

    def test_truncated_gzip_and_reversed_receipt_are_coverage_errors(self):
        (self.path / 'broken.json.gz').write_bytes(b'\x1f\x8b')
        self.snapshot('reversed.json.gz', '2026-11-07T16:00:00Z', received='2026-11-07T15:59:00Z')
        result = self.run_replay()
        self.assertEqual(len(result['snapshot_errors']), 2)
        self.assertEqual(result['coverage']['covered_games'], 0)

    def test_determinism_no_input_mutation_or_notes(self):
        self.snapshot('x.json.gz', '2026-11-07T16:00:00Z')
        original = copy.deepcopy(self.board)
        r = self.run_replay()
        self.assertEqual(r, self.run_replay())
        self.assertEqual(self.board, original)
        self.assertEqual(r['frozen_model'], self.cfg)


if __name__ == '__main__':
    unittest.main()
