#!/usr/bin/env python3
"""Descriptive research dashboard layered over the unchanged ronnie-v1 reporter."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest import evaluation as ev
from backtest import predictions_ledger as pl


def summarize(picks):
    graded = [p for p in picks if p['status'] == 'graded']
    n = len(graded)
    bins = {}
    for p in graded:
        k = min(int(p['probability'] * 10), 9)
        cell = bins.setdefault(k, {'n': 0, 'wins': 0, 'sum_probability': 0.0})
        cell['n'] += 1
        cell['wins'] += int(p['win'])
        cell['sum_probability'] += p['probability']
    calibration = []
    for k, c in sorted(bins.items()):
        calibration.append(dict(bin=f'{k/10:.1f}–{(k+1)/10:.1f}', n=c['n'], wins=c['wins'],
                                predicted=c['sum_probability']/c['n'], observed=c['wins']/c['n']))
    return dict(selected=len(picks), graded=n, pending=len(picks)-n,
                predicted_win_rate=sum(p['probability'] for p in graded)/n if n else None,
                observed_win_rate=sum(p['win'] for p in graded)/n if n else None,
                calibration=calibration, brier=pl.metrics(picks)['brier'])


def report(baseline, ledger, results, season, weeks=None):
    # --weeks declares expected coverage, never silently filters recorded weeks
    # out of the cumulative sample. Existing baseline reporting stays unchanged.
    expected = list(weeks or [])
    if len(expected) != len(set(expected)):
        raise ValueError('duplicate expected weeks')
    all_weeks = set(expected)
    for path in Path(ledger).glob('*.json'):
        entry = ev.read(path)
        pl.verify(entry)
        if entry['payload']['season'] == season:
            all_weeks.add(entry['payload']['week'])
    base = ev.report(baseline, ledger, results, season, sorted(all_weeks, key=lambda w: (len(w), w)))
    cumulative = {'ronnie': [], 'market_only': []}
    fully_graded = 0
    for week in base['weeks']:
        if 'graded' not in week:
            continue
        week['research'] = {}
        if week['eligible_for_cumulative']:
            fully_graded += 1
        for name, variant in week['graded']['variants'].items():
            week['research'][name] = summarize(variant['card'])
            if week['eligible_for_cumulative']:
                cumulative[name].extend(variant['card'])
    base['research'] = dict(fully_graded_prospective_weeks=fully_graded,
                            cumulative={name: summarize(picks) for name, picks in cumulative.items()},
                            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            warning='Descriptive selected-card observations, not independent trials or evidence of statistical significance. Pushes are losses. No profitability claim.')
    return base


def markdown(data):
    out = [ev.markdown(data), '# Research performance — descriptive only', '',
           f"Fully graded paired prospective weeks: **{data['research']['fully_graded_prospective_weeks']}**.", '']
    def display(scope, variants):
        out.extend([f'## {scope}', '', '| Variant | Selected | Graded n | Pending | Predicted win rate* | Observed win rate* | Brier |',
                    '| --- | --- | --- | --- | --- | --- | --- |'])
        def pct(x):
            return 'N/A' if x is None else f'{x:.1%}'
        for name, v in variants.items():
            brier = 'N/A' if v['brier'] is None else f"{v['brier']:.4f}"
            out.append(f"| {name} | {v['selected']} | {v['graded']} | {v['pending']} | {pct(v['predicted_win_rate'])} | {pct(v['observed_win_rate'])} | {brier} |")
        out.extend(['', '*Rates use the same graded picks only. Pending results are excluded.*', ''])
        for name, v in variants.items():
            out.extend([f'Calibration — {name} (n={v["graded"]}):', '',
                        '| Probability bin | n | Mean predicted | Observed |', '| --- | --- | --- | --- |'])
            for cell in v['calibration']:
                out.append(f"| {cell['bin']} | {cell['n']} | {pct(cell['predicted'])} | {pct(cell['observed'])} |")
            if not v['calibration']:
                out.append('| No graded observations | 0 | N/A | N/A |')
            out.append('')
    for week in data['weeks']:
        if 'research' in week:
            display(f"Week {week['week']} ({week['mode']}; paired eligible: {week['eligible_for_cumulative']})", week['research'])
    display('Cumulative eligible paired prospective weeks', data['research']['cumulative'])
    c = data['cumulative']
    out += [f"Cumulative expected points: Ronnie {c['ronnie_expected_points']:.2f}; market-only {c['market_only_expected_points']:.2f}.", '', data['research']['warning'], '']
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('baseline', 'ledger', 'season', 'output', 'markdown'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--results')
    parser.add_argument('--weeks', help='Expected weeks; all recorded weeks are also included')
    args = parser.parse_args()
    value = report(ev.read(args.baseline), args.ledger, ev.read(args.results) if args.results else [],
                   int(args.season), args.weeks.split(',') if args.weeks else None)
    pl.write_new(args.output, value)
    with open(args.markdown, 'x') as f:
        f.write(markdown(value))
    print(args.markdown)


if __name__ == '__main__':
    main()
