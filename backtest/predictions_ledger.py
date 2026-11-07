#!/usr/bin/env python3
"""Freeze weekly predictions before a deadline; grade only explicit final results.

No network calls, fitting, auto-submission or production changes. See docs/LEDGER.md.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest import snapshot_replay as sr
import beerpool as bp


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def record(board, manifest, snapshots, deadline, season, week, max_age_hours, historical=False):
    """Record one weekly decision. CLI supplies real clock; no backdating option."""
    board = json.loads(json.dumps(board))
    manifest = json.loads(json.dumps(manifest))
    started = now_utc()
    end = sr.utc(deadline)
    if not historical and started >= end:
        raise ValueError('prospective ledger must be recorded before submission deadline')
    if not historical and sr.utc(manifest['created_utc'], True) > started:
        raise ValueError('model freeze timestamp is in the future')
    if max_age_hours <= 0 or not math.isfinite(max_age_hours):
        raise ValueError('a positive finite snapshot age limit is required')
    numbers = [g['num'] for g in board['games']]
    if len(numbers) != len(set(numbers)):
        raise ValueError('duplicate game numbers in board')
    # Retrospective scenarios explicitly use the requested past decision. Prospective
    # predictions use information already available now, not later before deadline.
    decision = end if historical else started
    snapshot_data = sr.load_snapshots(snapshots)
    ronnie = sr.replay(board, manifest, snapshots, decision.isoformat(), max_age_hours, snapshot_data)
    benchmark_manifest = json.loads(json.dumps(manifest))
    benchmark = bp.Config(**benchmark_manifest['config']).with_(
        calibration=None, total_shrink=1.0, spread_shrink=1.0, huge_edge_p=None)
    benchmark_manifest['config'] = asdict(benchmark)
    market = sr.replay(board, benchmark_manifest, snapshots, decision.isoformat(), max_age_hours, snapshot_data)
    if ronnie['games'] != market['games'] or ronnie['snapshot_errors'] != market['snapshot_errors']:
        raise ValueError('snapshot inputs changed during recording; retry with a stable snapshot directory')
    metadata = []
    for g in board['games']:
        if not g.get('kickoff'):
            raise ValueError(f"missing kickoff for game {g['num']}")
        item = {k: g[k] for k in ('num', 'league', 'home', 'away', 'kickoff')}
        limits = [end, sr.utc(g['kickoff'])]
        lock = g.get('lock') or board.get('default_lock')
        if lock:
            limits.append(sr.utc(lock))
        item['effective_lock_utc'] = min(limits).isoformat()
        metadata.append(item)
    if not historical and any(g.get('receipt_verified') is False for g in ronnie['games']):
        raise ValueError('prospective ledger requires receipt timestamps; take fresh snapshots')
    # Store machine-gradeable predictions, including sheet lines, for every candidate
    # and selected slot. Pricing is never rerun during grading.
    for variant in (ronnie, market):
        candidates = {(c['game'], c['side']): c for c in variant['candidates']}
        for pick in variant['card']:
            pick['sheet_line'] = candidates[(pick['game'], pick['side'])]['sheet_line']
    finished = now_utc()
    if not historical and finished >= end:
        raise ValueError('recording finished after deadline; no prospective ledger written')
    if not historical:
        played = {g['num'] for g in metadata if sr.utc(g['effective_lock_utc']) <= finished}
        if any(c['game'] in played for v in (ronnie, market) for c in v['candidates']):
            raise ValueError('a predicted game locked before recording finished')
    payload = dict(schema=1, season=int(season), week=str(week), mode='historical' if historical else 'prospective',
                   recorded_utc=finished.isoformat(), decision_utc=decision.isoformat(),
                   submission_deadline_utc=end.isoformat(), games=metadata,
                   ledger_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   benchmark_definition='Raw market-implied sheet probabilities; no calibration, shrink, notes or huge-edge cap; same slot policy.',
                   variants={'ronnie': ronnie, 'market_only': market},
                   caveat='Prospective means recorded before games, not independently timestamp-attested or proven out-of-sample. Freeze training data separately.')
    return {'sha256': digest(payload), 'payload': payload}


def save_entry(directory, entry):
    # One entry per week prevents quietly replacing the official evaluation card.
    verify(entry)
    payload = entry['payload']
    def before_publish():
        if payload['mode'] == 'prospective':
            current = now_utc()
            if current < sr.utc(payload['recorded_utc']):
                raise ValueError('clock precedes recording time')
            if current >= sr.utc(payload['submission_deadline_utc']):
                raise ValueError('cannot persist a prospective ledger after deadline')
            predicted = {c['game'] for v in payload['variants'].values() for c in v['candidates']}
            if any(g['num'] in predicted and sr.utc(g['effective_lock_utc']) <= current for g in payload['games']):
                raise ValueError('cannot persist predictions after game lock')
    before_publish()
    week = payload['week']
    if not week or not all(ch.isalnum() or ch in '-_' for ch in week):
        raise ValueError('invalid week identifier')
    path = Path(directory) / f"{payload['season']}-wk{week}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_new(path, entry, before_publish)
    return path


def write_new(path, value, before_publish=None):
    data = json.dumps(value, indent=2, allow_nan=False) + '\n'
    path = Path(path)
    # Serialize and fsync privately before validating the actual publication time.
    # Hard-link publication is atomic and exclusive; failed writes leave no entry.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp') as tmp:
        tmp.write(data.encode())
        tmp.flush()
        os.fsync(tmp.fileno())
        if before_publish:
            before_publish()
        os.link(tmp.name, path)


def verify(entry):
    if entry['sha256'] != digest(entry['payload']) or entry['payload'].get('schema') != 1:
        raise ValueError('ledger integrity check failed')


def grade_pick(pick, game, result):
    if not math.isfinite(pick['sheet_line']):
        raise ValueError('invalid frozen sheet line')
    if pick['side'] == 'OVER':
        delta = result['home_score'] + result['away_score'] - pick['sheet_line']
    elif pick['side'] == 'UNDER':
        delta = pick['sheet_line'] - result['home_score'] - result['away_score']
    elif pick['side'] in (game['home'], game['away']):
        margin = result['home_score'] - result['away_score']
        delta = (margin if pick['side'] == game['home'] else -margin) + pick['sheet_line']
    else:
        raise ValueError('prediction side does not match game')
    return {'win': delta > 0, 'push': delta == 0}


def metrics(predictions):
    graded = [p for p in predictions if p['status'] == 'graded']
    n = len(graded)
    return dict(predictions=len(predictions), graded=n, pending=len(predictions) - n,
                wins=sum(p['win'] for p in graded), pushes=sum(p['push'] for p in graded),
                expected_wins=sum(p['probability'] for p in graded),
                brier=sum((p['probability'] - p['win']) ** 2 for p in graded) / n if n else None,
                log_loss=sum(-math.log(max(1e-15, p['probability'] if p['win'] else 1 - p['probability']))
                             for p in graded) / n if n else None)


def grade(entry, results):
    entry = json.loads(json.dumps(entry))
    results = json.loads(json.dumps(results))
    verify(entry)
    payload = entry['payload']
    games = {g['num']: g for g in payload['games']}
    matched, problems = {}, []
    seen = set()
    checked = now_utc()
    for r in results:
        if r.get('season') != payload['season'] or str(r.get('week')) != payload['week']:
            continue
        num = r['game']
        if num in seen:
            raise ValueError(f'duplicate result for game {num}')
        seen.add(num)
        g = games.get(num)
        if g is None:
            problems.append({'game': num, 'reason': 'game_not_in_ledger'})
            continue
        if (r.get('home'), r.get('away'), r.get('league')) != (g['home'], g['away'], g['league']) or sr.utc(r['kickoff']) != sr.utc(g['kickoff']):
            raise ValueError(f'result identity mismatch for game {num}')
        if r.get('status') != 'final':
            problems.append({'game': num, 'reason': 'not_final'})
            continue
        completed = sr.utc(r['completed_utc'], True)
        if completed > checked or completed < sr.utc(g['kickoff']):
            raise ValueError(f'invalid completion time for game {num}')
        for side in ('home_score', 'away_score'):
            if type(r.get(side)) is not int or r[side] < 0:
                raise ValueError(f'invalid final score for game {num}')
        matched[num] = r
    reports = {}
    for name, v in payload['variants'].items():
        def apply(predictions):
            out = []
            for p in predictions:
                if not math.isfinite(p['probability']) or not 0 <= p['probability'] <= 1:
                    raise ValueError('invalid frozen probability')
                g, r = games[p['game']], matched.get(p['game'])
                row = {**p, 'status': 'pending'}
                if r is not None:
                    row.update(status='graded', **grade_pick(p, g, r))
                out.append(row)
            return out
        card, candidates = apply(v['card']), apply(v['candidates'])
        m = metrics(card)
        m.update(earned_points=sum(p['points'] * p['win'] for p in card if p['status'] == 'graded'),
                 expected_points_graded=sum(p['points'] * p['probability'] for p in card if p['status'] == 'graded'),
                 expected_points_frozen=v['expected_points'],
                 complete_card=len(card) == 5, all_picks_final=bool(card) and all(p['status'] == 'graded' for p in card))
        reports[name] = dict(card=card, candidates=candidates, card_metrics=m,
                             candidate_metrics=metrics(candidates), coverage=v['coverage'])
    comparable = all(v['card_metrics']['complete_card'] and v['card_metrics']['all_picks_final'] for v in reports.values())
    difference = (reports['ronnie']['card_metrics']['earned_points'] - reports['market_only']['card_metrics']['earned_points']) if comparable else None
    return dict(schema=1, grader_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                ledger_sha256=entry['sha256'], season=payload['season'], week=payload['week'],
                mode=payload['mode'], results_sha256=digest(results), variants=reports,
                result_issues=problems, matched_final_games=len(matched),
                ronnie_minus_market_points=difference,
                caveat='Pushes lose. Pending/canceled games are ungraded. Candidate observations share outcomes; no independent-sample significance claim. Points are not monetary profit.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    rec = sub.add_parser('record')
    for arg in ('board', 'config', 'deadline', 'season', 'week', 'ledger', 'max-age-hours'):
        rec.add_argument('--' + arg, required=True)
    rec.add_argument('--snapshots', default=str(ROOT / 'data/snapshots'))
    rec.add_argument('--historical', action='store_true', help='Explicit retrospective scenario, never prospective evidence')
    gr = sub.add_parser('grade')
    for arg in ('entry', 'results', 'output'):
        gr.add_argument('--' + arg, required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(Path(path).read_text())
    if args.command == 'record':
        entry = record(read(args.board), read(args.config), args.snapshots, args.deadline,
                       args.season, args.week, float(args.max_age_hours), args.historical)
        print(save_entry(args.ledger, entry))
    else:
        write_new(args.output, grade(read(args.entry), read(args.results)))
        print(args.output)


if __name__ == '__main__':
    main()
