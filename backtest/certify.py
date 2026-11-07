#!/usr/bin/env python3
"""SYNTHETIC Week 10 rehearsal. No network, real picks or persistent observations.

Temporary fixtures and test clocks exercise actual parsing/recording/grading code.
Only a labeled summary survives. Requires existing production dependency pdftotext.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_board as bb
import snapshots
from backtest import evaluation as ev
from backtest import predictions_ledger as pl
from backtest import research_report as rr


def pdf(path, lines):
    """Minimal Courier PDF fixture using only the standard library."""
    def escape(s):
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = 'BT /F1 7 Tf 9 TL 20 570 Td\n' + '\n'.join('('+escape(line)+') Tj T*' for line in lines) + '\nET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1100 612] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
               ('<< /Length '+str(len(stream.encode()))+' >>\nstream\n'+stream+'\nendstream').encode()]
    data = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    data += f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    path.write_bytes(data)


def html():
    sections = []
    for market in ('spread', 'total'):
        rows = []
        for i in range(1, 6):
            for rot, team, line in [(2*i+99, f'Away {i}', '+4.5' if market == 'spread' else 'o46.5'),
                                    (2*i+100, f'Home {i}', '-4.5' if market == 'spread' else 'u46.5')]:
                rows.append(f'<tr><td>{rot} {team}</td>'+f'<td>{line} -110</td>'*10+'</tr>')
        sections.append(f'<tbody id="odds-table-{market}--1">'+''.join(rows)+'</tbody>')
    return '<!-- SYNTHETIC ONLY -->' + ''.join(sections)


def run():
    if not shutil.which('pdftotext'):
        raise RuntimeError('pdftotext is required; rehearsal cannot certify PDF ingestion without it')
    baseline = ev.read(ROOT / 'evaluation/baselines/ronnie-v1.json')
    ev.verify_baseline(baseline, check_sources=True)
    original_baseline = (ROOT / 'evaluation/baselines/ronnie-v1.json').read_bytes()
    with tempfile.TemporaryDirectory(prefix='SYNTHETIC-week10-') as tmp:
        root = Path(tmp)
        sheet = ['SYNTHETIC REHEARSAL ONLY - NOT A COMMISSIONER BOARD']
        for i in range(1, 8):
            time = '11:00 AM' if i == 7 else '3:30 PM'
            line = '-3' if i == 3 else '-2.5'
            sheet.append(f'{i:3}    Sat, Nov 14, 2026    {time}    Away {i}        at        Home {i}        TEST        H{i} {line}    45.5')
        pdf(root / 'SYNTHETIC.pdf', sheet)
        espn = {'events': [{'competitions': [{'competitors': [
            {'team': {'location': f'{side} {i}', 'abbreviation': f'{side[0]}{i}'}}
            for i in range(1, 8) for side in ('Away', 'Home')]}]}]}
        # Mock transport only: real pdftotext, board parser, HTML parser and builder.
        def fixture_fetch(url, *_):
            return json.dumps(espn) if 'espn' in url else html()
        with patch.object(bb, 'fetch', side_effect=fixture_fetch):
            board = bb.build(str(root / 'SYNTHETIC.pdf'), {'week': 'SYNTHETIC Week 10'}, None, False)
        assert len(board['games']) == 7
        # Poison embedded/live odds: replay must price only captured snapshots.
        for game in board['games']:
            game['market'] = {'fav': game['home'], 'spread': 99, 'total': 99}
        captured = datetime(2026, 11, 14, 16, tzinfo=timezone.utc)
        class SyntheticClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 14, 16, 0, 1, tzinfo=timezone.utc)
        with patch.object(snapshots, 'SNAP_DIR', str(root / 'snapshots')), \
             patch.object(snapshots, 'fetch', return_value=html()), \
             patch.object(snapshots, 'datetime', SyntheticClock):
            with redirect_stdout(io.StringIO()):
                paths = snapshots.take(captured)
        assert len(paths) == 2
        before_lock = datetime(2026, 11, 14, 16, 30, tzinfo=timezone.utc)
        with patch.object(pl, 'now_utc', return_value=before_lock):
            entry = ev.record(baseline, board, root / 'snapshots', '2026-11-14T12:00', 2026, '10')
            assert all(len(v['card']) == 5 for v in entry['payload']['variants'].values())
            # Exercise the real prospective save checks, but relabel at the
            # write boundary so no test-clock observation is ever persisted as real.
            original_write = pl.write_new
            def synthetic_write(path, value, before_publish=None):
                safe = json.loads(json.dumps(value))
                safe['payload'].update(mode='synthetic', synthetic=True)
                safe['sha256'] = pl.digest(safe['payload'])
                original_write(path, safe, before_publish)
            ledger = root / 'ledger'
            with patch.object(pl, 'write_new', side_effect=synthetic_write):
                path = pl.save_entry(ledger, entry)
                try:
                    pl.save_entry(ledger, entry)
                except FileExistsError:
                    pass
                else:
                    raise AssertionError('ledger overwrite allowed')
            entry = ev.read(path)
            assert entry['payload']['mode'] == 'synthetic'
            assert all(row['market'].endswith(' -4.5')
                       for row in entry['payload']['variants']['ronnie']['sweep'] if 'market' in row)
        statuses = {g['game']: g['status'] for g in entry['payload']['variants']['ronnie']['games']}
        assert statuses[7] == 'locked_before_submission'
        assert statuses[6] == 'no_matching_pre_deadline_snapshot'
        for when in (datetime(2026, 11, 14, 17, tzinfo=timezone.utc), captured):
            # Deadline equality rejects; a decision before receipt produces no observations.
            with patch.object(pl, 'now_utc', return_value=when):
                try:
                    trial = ev.record(baseline, board, root / 'snapshots', '2026-11-14T12:00', 2026, '10')
                except ValueError:
                    assert when.hour == 17
                else:
                    assert all(not v['candidates'] for v in trial['payload']['variants'].values())
        scores = [(24, 20), (21, 24), (24, 21), (17, 10), (10, 14)]
        finals = [dict(season=2026, week='10', game=i, league='CFB', home=f'H{i}', away=f'A{i}',
                       kickoff='2026-11-14T15:30', status='final', home_score=h, away_score=a,
                       completed_utc='2026-11-15T00:00:00Z', synthetic=True,
                       verification=dict(source_url='https://synthetic.invalid/not-real', event_id=f'SYNTHETIC-{i}',
                                         checked_utc='2026-11-15T01:00:00Z'))
                  for i, (h, a) in enumerate(scores, 1)]
        pl.write_new(root / 'SYNTHETIC-results.json', finals)
        with patch.object(pl, 'now_utc', return_value=datetime(2026, 11, 15, 4, tzinfo=timezone.utc)):
            pending = rr.report(baseline, ledger, finals[:2], 2026, ['10', '11'])
            final = rr.report(baseline, ledger, ev.read(root / 'SYNTHETIC-results.json'), 2026, ['10', '11'])
        assert pending['weeks'][0]['graded']['ronnie_minus_market_points'] is None
        assert final['weeks'][1]['status'] == 'not_recorded'
        assert final['research']['fully_graded_prospective_weeks'] == 0
        assert final['cumulative']['paired_weeks'] == 0
        for name, v in final['weeks'][0]['graded']['variants'].items():
            expected = sum(p['points'] * (scores[p['game']-1][0]-scores[p['game']-1][1] + p['sheet_line'] > 0)
                           for p in v['card'])
            assert v['card_metrics']['earned_points'] == expected
            assert any(p['push'] for p in v['card'])
        pl.write_new(root / 'SYNTHETIC-report.json', final)
        (root / 'SYNTHETIC-report.md').write_text('SYNTHETIC ONLY\n\n' + rr.markdown(final))
        assert 'synthetic' in (root / 'SYNTHETIC-report.md').read_text()
        assert ev.read(path)['payload']['mode'] == 'synthetic'
        assert original_baseline == (ROOT / 'evaluation/baselines/ronnie-v1.json').read_bytes()
        return dict(label='SYNTHETIC REHEARSAL — NOT PROSPECTIVE EVIDENCE', passed=True,
                    baseline_sha256=baseline['sha256'], ingested_games=7, captures=2,
                    picks_per_variant=5, missing_games=1, earlier_locked_games=1,
                    missing_week='11', fully_graded_prospective_weeks=0,
                    temporary_artifacts='deleted on completion', network='mocked transport; real PDF/HTML parsing, pricing, ledger and grading')


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
