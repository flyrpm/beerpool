#!/usr/bin/env python3
"""Versioned forward-evaluation policy, ledger recording and descriptive reports.

No fitting, network requests, automatic submission or production model changes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import beerpool as bp
from backtest import predictions_ledger as pl
from backtest import snapshot_replay as sr

SOURCES = ('beerpool.py', 'build_board.py', 'vi_parse.py', 'snapshots.py',
           'backtest/snapshot_replay.py', 'backtest/predictions_ledger.py', 'backtest/evaluation.py')


def read(path):
    return json.loads(Path(path).read_text())


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def create_baseline(identifier):
    if git('status', '--porcelain'):
        raise ValueError('commit all tooling changes before freezing a baseline')
    model = sr.freeze()
    cfg = bp.Config(**model['config'])
    benchmark = asdict(cfg.with_(calibration=None, total_shrink=1.0, spread_shrink=1.0, huge_edge_p=None))
    payload = dict(schema=1, id=identifier, git_commit=git('rev-parse', 'HEAD'),
                   created_utc=pl.now_utc().isoformat(), source_sha256=source_hashes(),
                   frozen_model=model, model_config_sha256=pl.digest(model['config']),
                   calibration_sha256=pl.digest(model['config']['calibration']),
                   calibration_file_sha256=hashlib.sha256(Path(bp.CALIBRATION_PATH).read_bytes()).hexdigest(),
                   benchmark_config=benchmark, benchmark_config_sha256=pl.digest(benchmark),
                   snapshot_policy=dict(max_age_hours=24, require_receipt=True, strictly_before_decision=True),
                   submission_policy=dict(timezone='America/New_York', deadline='explicit deadline must equal original board default_lock',
                                          game_lock='earliest of explicit/default game lock, kickoff, submission deadline',
                                          publication='before every predicted game lock; one evaluation record per season/week'),
                   pool_rules=dict(slot_points=[5, 5, 3, 3, 3], push='loss', mega=False,
                                   banned_teams=sorted(bp.BANNED_TEAMS), five_blocking_tags=sorted(bp.NO_FIVE_TAGS if cfg.big_move_caps else bp.NO_FIVE_TAGS - {"big_move"}),
                                   uniqueness='one game and one explicit thesis per card; distinct environments in five-point slots',
                                   sweet_spot='existing Config policy, with existing fallback; maximize legal expected points',
                                   spread_book_tolerance=bp.BOOK_SPREAD_TOLERANCE,
                                   total_book_tolerance=bp.BOOK_TOTAL_TOLERANCE,
                                   big_move_points=bp.BIG_MOVE, steam_points=bp.STEAM),
                   evaluation_policy='No fitting or tuning from prospective results. Descriptive paired totals use only complete, final, prospective weeks on this exact baseline.',
                   evidence_limit='Software and recording timestamps do not establish independent training data, external submission, profitability or superiority.')
    return {'sha256': pl.digest(payload), 'payload': payload}


def verify_baseline(baseline, check_sources=False):
    """check_sources=True: this checkout must BE the pinned engine (required to record).
    check_sources='revision': only prove the pinned hashes belong to the pinned git commit
    (used on main, where a newer engine version lives; run v1 from pinned_checkout())."""
    p = baseline['payload']
    if baseline['sha256'] != pl.digest(p) or p.get('schema') != 1:
        raise ValueError('baseline integrity check failed')
    cfg = p['frozen_model']['config']
    expected_benchmark = asdict(bp.Config(**cfg).with_(calibration=None, total_shrink=1.0,
                                                     spread_shrink=1.0, huge_edge_p=None))
    if (p['model_config_sha256'] != pl.digest(cfg)
            or p['calibration_sha256'] != pl.digest(cfg['calibration'])
            or p['benchmark_config_sha256'] != pl.digest(p['benchmark_config'])
            or p['benchmark_config'] != {k: expected_benchmark.get(k) for k in p['benchmark_config']}
            or any(expected_benchmark[k] != getattr(bp.Config(), k)
                   for k in expected_benchmark if k not in p['benchmark_config'])):
        raise ValueError('baseline configuration hashes or benchmark mismatch')
    if check_sources:
        if check_sources is True and p['source_sha256'] != source_hashes():
            raise ValueError('baseline source mismatch; run from its pinned checkout: '
                             'python3 backtest/evaluation.py pin --baseline <file> --dest <dir>')
        # Check that hashes really belong to the stated Git revision, not just to
        # the current working directory. Reading history does not mutate it.
        for name, sha in p['source_sha256'].items():
            raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', f"{p['git_commit']}:{name}"])
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ValueError('baseline Git revision does not match sources')


def frozen_commit(baseline, limit=500):
    """Newest ancestor of HEAD whose pinned sources are byte-identical to the baseline:
    the frozen engine with the newest operational tooling around it."""
    want = baseline['payload']['source_sha256']
    for rev in git('rev-list', '-n', str(limit), 'HEAD').split():
        try:
            ok = all(hashlib.sha256(subprocess.check_output(
                ['git', '-C', str(ROOT), 'show', f'{rev}:{name}'], stderr=subprocess.DEVNULL)
            ).hexdigest() == sha for name, sha in want.items())
        except subprocess.CalledProcessError:
            ok = False
        if ok:
            return rev
    raise ValueError('no ancestor commit carries the baseline sources (shallow clone? fetch history)')


def pinned_checkout(baseline, dest):
    """A detached git worktree where this baseline's engine is the code that runs.
    Recording v1 happens there; main may carry a newer engine version."""
    verify_baseline(baseline, check_sources='revision')
    rev = frozen_commit(baseline)
    dest = Path(dest).resolve()
    if not dest.exists():
        subprocess.check_call(['git', '-C', str(ROOT), 'worktree', 'add', '--detach', '-q',
                               str(dest), rev])
    head = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
    if head != rev:
        raise ValueError(f'{dest} is at {head}, not the frozen-engine commit {rev}')
    return dest


def record(baseline, board, snapshots, deadline, season, week):
    verify_baseline(baseline, check_sources=True)
    policy = baseline['payload']
    if sr.utc(policy['created_utc'], True) > pl.now_utc():
        raise ValueError('baseline creation time is in the future')
    if not board.get('default_lock') or sr.utc(board['default_lock']) != sr.utc(deadline):
        raise ValueError('explicit deadline must equal the original board default_lock')
    entry = pl.record(board, policy['frozen_model'], snapshots, deadline, season, week,
                      policy['snapshot_policy']['max_age_hours'])
    # Validate both frozen configurations, not merely a human-readable label.
    if entry['payload']['variants']['market_only']['frozen_model']['config'] != policy['benchmark_config']:
        raise ValueError('benchmark does not match baseline')
    entry['payload'].update(baseline_id=policy['id'], baseline_sha256=baseline['sha256'],
                            baseline_git_commit=policy['git_commit'], operating_git_commit=git('rev-parse', 'HEAD'))
    entry['sha256'] = pl.digest(entry['payload'])
    return entry


def verify_results(results):
    """Require an operator-verified, source-cited final export; never infer finals."""
    for r in results:
        if r.get('status') != 'final':
            continue
        evidence = r.get('verification', {})
        url = urlparse(evidence.get('source_url', ''))
        if url.scheme != 'https' or not url.netloc:
            raise ValueError('final results require verification.source_url (HTTPS)')
        if not evidence.get('event_id'):
            raise ValueError('final results require verification.event_id')
        checked = sr.utc(evidence['checked_utc'], True)
        if checked < sr.utc(r['completed_utc'], True) or checked > pl.now_utc():
            raise ValueError('invalid final-result verification time')


def report(baseline, ledger_dir, results, season, weeks=None):
    verify_baseline(baseline)
    verify_results(results)
    entries = {}
    for path in sorted(Path(ledger_dir).glob('*.json')):
        entry = read(path)
        pl.verify(entry)
        p = entry['payload']
        if p['season'] != season:
            continue
        if p['week'] in entries:
            raise ValueError(f"duplicate ledger week: {p['week']}")
        entries[p['week']] = entry
    selected = list(weeks) if weeks is not None else sorted(entries, key=lambda w: (len(w), w))
    if len(selected) != len(set(selected)):
        raise ValueError('duplicate report weeks')
    output = []
    totals = dict(paired_weeks=0, ronnie_points=0, market_only_points=0, differential=0,
                  ronnie_expected_points=0.0, market_only_expected_points=0.0)
    for week in selected:
        if week not in entries:
            output.append(dict(week=week, status='not_recorded', warnings=['No frozen prediction record.']))
            continue
        entry = entries[week]
        p = entry['payload']
        graded = pl.grade(entry, results)
        warnings = sorted(set(w for variant in p['variants'].values() for w in variant['warnings']))
        coverage_details = {}
        for name, variant in p['variants'].items():
            coverage_details[name] = {k: variant[k] for k in ('coverage', 'games', 'snapshot_errors', 'sweep')}
            missing = variant['coverage']['uncovered_games']
            if missing:
                warnings.append(f'{name}: {missing} games excluded or without matching observations.')
            if variant['snapshot_errors']:
                warnings.append(f"{name}: {len(variant['snapshot_errors'])} snapshot input errors.")
            partial = sum(g['status'] == 'covered' and not all(g['markets'].values())
                          for g in variant['games'])
            if partial:
                warnings.append(f'{name}: {partial} matched games missing spread or total markets.')
        if graded['result_issues']:
            warnings.append(f"{len(graded['result_issues'])} result records ungraded; see result_issues.")
        eligible = p['mode'] == 'prospective' and p.get('baseline_sha256') == baseline['sha256']
        expected_configs = {'ronnie': baseline['payload']['frozen_model']['config'],
                            'market_only': baseline['payload']['benchmark_config']}
        if any(p['variants'][name]['frozen_model']['config'] != cfg for name, cfg in expected_configs.items()):
            eligible = False
            warnings.append('Configurations differ from this baseline; excluded from cumulative comparison.')
        if not eligible:
            warnings.append('Historical or different/missing baseline; excluded from cumulative comparison.')
        if sr.utc(p['decision_utc']) < sr.utc(baseline['payload']['created_utc'], True):
            eligible = False
            warnings.append('Decision predates baseline freeze; excluded from cumulative comparison.')
        complete = graded['ronnie_minus_market_points'] is not None
        if not complete:
            warnings.append('Incomplete cards or pending finals; excluded from paired cumulative totals.')
        row = dict(week=week, status='final' if complete else 'pending_or_incomplete',
                   mode=p['mode'], eligible_for_cumulative=eligible and complete,
                   decision_utc=p['decision_utc'], recorded_utc=p['recorded_utc'],
                   ledger_sha256=entry['sha256'], graded=graded, coverage_details=coverage_details, warnings=warnings)
        output.append(row)
        if eligible and complete:
            totals['paired_weeks'] += 1
            for name in ('ronnie', 'market_only'):
                metrics = graded['variants'][name]['card_metrics']
                totals[name + '_points'] += metrics['earned_points']
                totals[name + '_expected_points'] += metrics['expected_points_frozen']
            totals['differential'] += graded['ronnie_minus_market_points']
    return dict(schema=1, baseline_id=baseline['payload']['id'], baseline_sha256=baseline['sha256'],
                season=season, results_sha256=pl.digest(results), weeks=output, cumulative=totals,
                reporting_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                caveat='Engineering checks passed does not mean predictive superiority. No profitability claim; prospective sample size and uncertainty still matter.')


def markdown(data):
    out = [f"# Ronnie Mooch evaluation — {data['season']}", '',
           f"Baseline: `{data['baseline_id']}` (`{data['baseline_sha256']}`).", '']
    for row in data['weeks']:
        out += [f"## Week {row['week']} — {row['status']}", '']
        if 'graded' in row:
            out += [f"Mode: {row['mode']}; recorded {row['recorded_utc']}.", '']
            for name, v in row['graded']['variants'].items():
                m = v['card_metrics']
                actual = str(m['earned_points']) if m['all_picks_final'] else f"{m['earned_points']} so far; {m['pending']} pending"
                out += [f"### {name}", '',
                        f"Expected: {m['expected_points_frozen']:.2f}; actual: {actual}.", '',
                        '| Slot | Game | Selection | Points | Probability | Result |',
                        '| --- | --- | --- | --- | --- | --- |']
                for p in v['card']:
                    result = 'pending' if p['status'] != 'graded' else ('win' if p['win'] else 'push (loss)' if p['push'] else 'loss')
                    label = p['label'].replace('|', '\\|').replace('\n', ' ')
                    out += [f"| {p['slot']} | {p['game']} | {label} | {p['points']} | {p['probability']:.3f} | {result} |"]
                c = v['coverage']
                out += ['', f"Coverage: {c['covered_games']}/{c['total_games']} games; {c['uncovered_games']} uncovered.", '']
            delta = row['graded']['ronnie_minus_market_points']
            out += [f"Ronnie − benchmark: {delta if delta is not None else 'pending / not comparable'}.", '']
        out += ['Warnings:', ''] + ['- ' + w for w in row['warnings']] + ['']
    c = data['cumulative']
    out += ['## Cumulative paired prospective performance', '',
            f"Completed comparable weeks: {c['paired_weeks']}; Ronnie: {c['ronnie_points']}; "
            f"benchmark: {c['market_only_points']}; difference: {c['differential']}.", '', data['caveat'], '']
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('freeze')
    b.add_argument('--id', required=True)
    b.add_argument('--output', required=True)
    rec = sub.add_parser('record')
    for name in ('baseline', 'board', 'deadline', 'season', 'week', 'ledger'):
        rec.add_argument('--' + name, required=True)
    rec.add_argument('--snapshots', default=str(ROOT / 'data/snapshots'))
    pin = sub.add_parser('pin', help='create/verify the pinned checkout this baseline records from')
    pin.add_argument('--baseline', required=True)
    pin.add_argument('--dest', required=True)
    rep = sub.add_parser('report')
    for name in ('baseline', 'ledger', 'season', 'output', 'markdown'):
        rep.add_argument('--' + name, required=True)
    rep.add_argument('--results', help='Verified results JSON; omit while no finals are available')
    rep.add_argument('--weeks', help='Comma-separated expected weeks; missing records are reported')
    args = parser.parse_args()
    if args.command == 'freeze':
        pl.write_new(args.output, create_baseline(args.id))
    elif args.command == 'pin':
        print(pinned_checkout(read(args.baseline), args.dest))
    elif args.command == 'record':
        entry = record(read(args.baseline), read(args.board), args.snapshots, args.deadline, int(args.season), args.week)
        print(pl.save_entry(args.ledger, entry))
    else:
        value = report(read(args.baseline), args.ledger, read(args.results) if args.results else [],
                       int(args.season), args.weeks.split(',') if args.weeks else None)
        pl.write_new(args.output, value)
        with open(args.markdown, 'x') as f:
            f.write(markdown(value))
        print(args.markdown)


if __name__ == '__main__':
    main()
