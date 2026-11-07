#!/usr/bin/env python3
"""Offline single-submission replay; never reads board markets or closing odds.

Freeze: python3 backtest/snapshot_replay.py freeze --output frozen.json
Replay: python3 backtest/snapshot_replay.py replay --board board.json --config frozen.json \
    --deadline 2026-11-07T12:00 --snapshots data/snapshots --output replay.json
Naive decision/board times mean America/New_York. Snapshot times must carry a zone.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import beerpool as bp
import build_board as bb
import vi_parse


def utc(value, require_zone=False):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        if require_zone:
            raise ValueError('snapshot timestamps must include a timezone')
        t = t.replace(tzinfo=ZoneInfo('America/New_York'))
    return t.astimezone(timezone.utc)


def fingerprint():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('beerpool.py', 'build_board.py', 'vi_parse.py',
                         'backtest/snapshot_replay.py')}


def freeze(cfg=None):
    # JSON round-trip detaches calibration dictionaries from mutable caller state.
    return json.loads(json.dumps(dict(schema=1, created_utc=datetime.now(timezone.utc).isoformat(),
                                     source_sha256=fingerprint(),
                                     config=asdict(cfg if cfg is not None else bp.Config.production()))))


def load_snapshots(directory):
    good, errors = [], []
    for path in sorted(Path(directory).rglob('*.json.gz')):
        try:
            with gzip.open(path, 'rt') as f:
                s = json.load(f)
            taken = utc(s['taken_utc'], require_zone=True)
            received = utc(s.get('received_utc', s['taken_utc']), require_zone=True)
            if s['books'] != vi_parse.BOOKS:
                raise ValueError('unsupported book column order')
            if s['league'] not in ('NFL', 'CFB') or not isinstance(s['rows'], list):
                raise ValueError('invalid league/rows')
            good.append((max(taken, received), str(path), s))
        except (OSError, ValueError, KeyError, TypeError) as e:
            errors.append({'path': str(path), 'error': str(e)})
    return sorted(good, key=lambda x: (x[0], x[1]), reverse=True), errors


def replay(board, manifest, directory, deadline, max_age_hours=None):
    manifest = json.loads(json.dumps(manifest))
    # Fail closed if a different implementation would reinterpret frozen settings.
    if manifest.get('schema') != 1 or manifest['source_sha256'] != fingerprint():
        raise ValueError('frozen configuration source mismatch; use its original checkout')
    cfg = bp.Config(**json.loads(json.dumps(manifest['config'])))
    decision = utc(deadline)
    snapshots, errors = load_snapshots(directory)
    warnings = ['Replay does not establish out-of-sample performance: verify model training cutoff.',
                'Embedded board markets, notes and MEGA requests are ignored.']
    if utc(manifest['created_utc'], require_zone=True) >= decision:
        warnings.append('Configuration was frozen at/after the decision; this is a retrospective scenario.')
    if max_age_hours is None:
        warnings.append('No snapshot age limit specified; inspect age_seconds for stale observations.')
    if max_age_hours is not None and max_age_hours <= 0:
        raise ValueError('max_age_hours must be positive')
    records, games = [], []
    for original in board['games']:
        g = {k: v for k, v in original.items() if k not in ('market', 'notes')}
        rec = {'game': g['num'], 'league': g.get('league', 'NFL'), 'markets': {}}
        lock_value = g.get('lock') or board.get('default_lock')
        limits = [decision]
        for t in (lock_value, g.get('kickoff')):
            if t:
                limits.append(utc(t))
        cutoff = min(limits)
        rec['cutoff_utc'] = cutoff.isoformat()
        if cutoff < decision:
            rec['status'] = 'locked_before_submission'
            records.append(rec)
            continue
        # Reuse current market ingestion, with original full names where available.
        away, home = g.get('away_name'), g.get('home_name')
        if (not away or not home) and ' at ' in g.get('names', ''):
            away, home = g['names'].split(' at ', 1)
        if not away or not home:
            rec['status'] = 'missing_full_team_names'
            records.append(rec)
            continue
        g['away_name'], g['home_name'] = away, home
        chosen = None
        for observed, path, snap in snapshots:
            if snap['league'] != rec['league'] or observed >= cutoff:
                continue
            if max_age_hours is not None and cutoff - observed > timedelta(hours=max_age_hours):
                continue
            # Do not combine markets from different snapshots or backfill missing markets.
            market = bb.market_for(g, snap)
            if market:
                chosen = observed, path, snap, market
                break
        if chosen is None:
            rec['status'] = 'no_matching_pre_deadline_snapshot'
            records.append(rec)
            continue
        observed, path, snap, market = chosen
        market['fav'] = (g['home'] if market.get('fav') == 'HOME' else
                         g['away'] if market.get('fav') == 'AWAY' else None)
        g['market'] = market
        # Explicit lock in one common timezone avoids aware/naive comparison errors.
        g['lock'] = cutoff.isoformat()
        games.append(g)
        rec.update(status='covered', snapshot=path, taken_utc=snap['taken_utc'],
                   available_utc=observed.isoformat(), age_seconds=(cutoff - observed).total_seconds(),
                   receipt_verified='received_utc' in snap,
                   snapshot_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
        rec['markets'] = {'spread': market.get('spread') is not None,
                          'total': market.get('total') is not None}
        records.append(rec)
    priced_board = {'week': board.get('week', '?'), 'games': games}
    candidates, sweep = bp.build_candidates(priced_board, decision - timedelta(microseconds=1), warnings, cfg)
    card, thin, _ = bp.build_card(candidates, cfg=cfg)
    # Book conflicts / missing sheet markets can leave a covered game unpriceable.
    for rec in records:
        rec['candidate_count'] = sum(c.game == rec['game'] for c in candidates)
    covered = sum(r['status'] == 'covered' for r in records)
    if any(r.get('receipt_verified') is False for r in records):
        warnings.append('Legacy snapshots record capture start only; receipt before cutoff cannot be verified.')
    if len(card) < 5:
        warnings.append(f'Incomplete legal card: {len(card)}/5 picks; no future-odds fallback used.')
    return dict(schema=1, decision_utc=decision.isoformat(), frozen_model=manifest,
                board_sha256=hashlib.sha256(json.dumps(board, sort_keys=True).encode()).hexdigest(),
                max_age_hours=max_age_hours, coverage={'total_games': len(records), 'covered_games': covered,
                'uncovered_games': len(records) - covered}, games=records, snapshot_errors=errors,
                warnings=warnings, sweep=sweep, thin=thin,
                expected_points=sum((5 if i < 2 else 3) * c.p for i, c in enumerate(card)),
                candidates=[dict(game=c.game, side=c.side, label=c.label, sheet_line=c.sheet_line,
                                 market_line=c.market_line, probability=c.p,
                                 five_eligible=c.five_eligible) for c in candidates],
                card=[dict(slot=i + 1, points=5 if i < 2 else 3, game=c.game,
                           side=c.side, label=c.label, probability=c.p) for i, c in enumerate(card)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    f = sub.add_parser('freeze')
    f.add_argument('--output', required=True)
    r = sub.add_parser('replay')
    for name in ('board', 'config', 'deadline', 'output'):
        r.add_argument('--' + name, required=True)
    r.add_argument('--snapshots', default=str(ROOT / 'data/snapshots'))
    r.add_argument('--max-age-hours', type=float)
    args = ap.parse_args()
    if args.command == 'freeze':
        result = freeze()
    else:
        result = replay(json.loads(Path(args.board).read_text()), json.loads(Path(args.config).read_text()),
                        args.snapshots, args.deadline, args.max_age_hours)
    # Exclusive creation keeps frozen manifests and replay artifacts immutable by default.
    with open(args.output, 'x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
