"""Storage regressions: immutable, complete captures even with identical clocks."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import snapshots


class SnapshotStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.when = datetime(2026, 11, 7, 16, 0, 0, tzinfo=timezone.utc)

    def test_two_snapshots_in_same_minute_never_overwrite(self):
        with patch.object(snapshots, 'SNAP_DIR', str(self.root)), \
             patch.object(snapshots, 'SOURCES', {'NFL': 'https://example.test'}), \
             patch.object(snapshots, 'fetch', return_value='html'), \
             patch.object(snapshots.vi_parse, 'parse', side_effect=[
                 {'rows': [{'first': True}]}, {'rows': [{'second': True}]}]):
            first = Path(snapshots.take(self.when)[0])
            original_bytes = first.read_bytes()
            # Exactly the same microsecond is stronger than same-minute coverage.
            second = Path(snapshots.take(self.when)[0])
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original_bytes)
        self.assertEqual(len(list(self.root.rglob('*.json.gz'))), 2)
        self.assertEqual(json.loads(gzip.decompress(second.read_bytes()))['rows'], [{'second': True}])
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def test_uuid_collision_fails_without_replacing_existing_capture(self):
        with patch.object(snapshots, 'SNAP_DIR', str(self.root)), \
             patch.object(snapshots, 'SOURCES', {'NFL': 'https://example.test'}), \
             patch.object(snapshots, 'fetch', return_value='html'), \
             patch.object(snapshots.vi_parse, 'parse', return_value={'rows': [{}]}), \
             patch.object(snapshots, 'uuid4') as uid:
            uid.return_value.hex = 'fixed'
            first = Path(snapshots.take(self.when)[0])
            original_bytes = first.read_bytes()
            with self.assertRaises(FileExistsError):
                snapshots.take(self.when)
            self.assertEqual(first.read_bytes(), original_bytes)
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def test_market_at_uses_payload_receipt_not_filename_order(self):
        day = self.root / '2026-11-07'
        day.mkdir()
        for name, receipt in [('z_NFL_old.json.gz', '2026-11-07T16:01:00+00:00'),
                              ('a_NFL_new.json.gz', '2026-11-07T16:02:00+00:00')]:
            with gzip.open(day / name, 'wt') as f:
                json.dump({'league': 'NFL', 'taken_utc': self.when.isoformat(),
                           'received_utc': receipt, 'rows': []}, f)
        with patch.object(snapshots, 'SNAP_DIR', str(self.root)):
            self.assertEqual(snapshots.market_at('2026-11-07T16:01:30Z')['NFL']['received_utc'],
                             '2026-11-07T16:01:00+00:00')
            self.assertEqual(snapshots.market_at('2026-11-07T16:03:00Z')['NFL']['received_utc'],
                             '2026-11-07T16:02:00+00:00')

    def test_failed_publication_leaves_no_partial_capture(self):
        with patch.object(snapshots, 'SNAP_DIR', str(self.root)), \
             patch.object(snapshots, 'SOURCES', {'NFL': 'https://example.test'}), \
             patch.object(snapshots, 'fetch', return_value='html'), \
             patch.object(snapshots.vi_parse, 'parse', return_value={'rows': [{}]}), \
             patch.object(snapshots.os, 'link', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                snapshots.take(self.when)
        self.assertEqual(list(self.root.rglob('*.*')), [])


if __name__ == '__main__':
    unittest.main()
