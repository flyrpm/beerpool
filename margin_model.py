#!/usr/bin/env python3
"""Empirical NFL margin / total distributions (Phase 3 of the redesign).

  python3 margin_model.py fit      # fit on nflverse games, write models/nfl_empirical.json
  python3 margin_model.py eval     # out-of-sample test vs the hand-tuned parametric model

Replaces "normal curve x hand-set key-number bumps" with what actually happened:
P(home margin = k | closing spread ~ s) and P(total = t | closing total ~ T), estimated
with a Gaussian kernel over the closing number. Key numbers (3, 7, 10, 6, 14...) come out
of the data instead of being typed in. Both orientations of each game are used (home
margin m at spread s == -m at -s), which doubles the data and keeps it symmetric.

Data: nflverse games.csv (https://github.com/nflverse/nfldata), closing lines + scores.
Convention there: spread_line > 0 means the HOME team is favoured; result = home - away.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "data", "hist", "nfl_games.csv")
OUT = os.path.join(ROOT, "models", "nfl_empirical.json")
URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

SPREAD_GRID = [x / 2 for x in range(-50, 51)]      # expected home margin -25..+25
TOTAL_GRID = [x / 2 for x in range(60, 141)]       # 30..70
MARGIN_RANGE = range(-60, 61)
TOTAL_RANGE = range(0, 121)
BW_SPREAD, BW_TOTAL = 1.25, 1.5                    # kernel bandwidths (points)
SMOOTH = 0.15                                      # mix with a smooth normal to fill holes


def load(seasons: range):
    if not os.path.exists(CSV):
        import urllib.request
        os.makedirs(os.path.dirname(CSV), exist_ok=True)
        urllib.request.urlretrieve(URL, CSV)
    out = []
    for r in csv.DictReader(open(CSV)):
        try:
            season = int(r["season"])
            if season not in seasons or not r["result"] or not r["spread_line"]:
                continue
            out.append(dict(season=season, s=float(r["spread_line"]), m=int(float(r["result"])),
                            T=float(r["total_line"]) if r["total_line"] else None,
                            t=int(float(r["total"])) if r["total"] else None))
        except ValueError:
            continue
    return out


def _normal(k, mu, sd):
    return math.exp(-0.5 * ((k - mu) / sd) ** 2)


def kernel_table(pairs, grid, support, bw, sd_smooth):
    """pairs: (line, outcome). Returns {grid point: pmf over support}."""
    table = {}
    for g in grid:
        w = {}
        tot = 0.0
        for x, y in pairs:
            d = (x - g) / bw
            if abs(d) > 4:
                continue
            wt = math.exp(-0.5 * d * d)
            w[y] = w.get(y, 0.0) + wt
            tot += wt
        sm = {k: _normal(k, g, sd_smooth) for k in support}
        zs = sum(sm.values())
        pmf = {}
        for k in support:
            emp = w.get(k, 0.0) / tot if tot else 0.0
            pmf[k] = (1 - SMOOTH) * emp + SMOOTH * sm[k] / zs
        z = sum(pmf.values())
        table[g] = {k: v / z for k, v in pmf.items()}
    return table


def fit(seasons=range(2006, 2026)):
    games = load(seasons)
    mpairs = [(g["s"], g["m"]) for g in games] + [(-g["s"], -g["m"]) for g in games]
    tpairs = [(g["T"], g["t"]) for g in games if g["T"] is not None and g["t"] is not None]
    model = {"meta": {"seasons": [seasons.start, seasons.stop - 1], "games": len(games),
                      "bw_spread": BW_SPREAD, "bw_total": BW_TOTAL, "smooth": SMOOTH},
             "margin": {str(g): {str(k): round(v, 6) for k, v in p.items() if v > 1e-6}
                        for g, p in kernel_table(mpairs, SPREAD_GRID, MARGIN_RANGE, BW_SPREAD, 13.5).items()},
             "total": {str(g): {str(k): round(v, 6) for k, v in p.items() if v > 1e-6}
                       for g, p in kernel_table(tpairs, TOTAL_GRID, TOTAL_RANGE, BW_TOTAL, 13.0).items()}}
    return model


# ---------------------------------------------------------------- lookup (used by beerpool)
_CACHE: dict = {}


def load_model(path: str = OUT) -> dict | None:
    if path not in _CACHE:
        _CACHE[path] = json.load(open(path)) if os.path.exists(path) else None
    return _CACHE[path]


def _interp(table: dict, x: float, lo: float, hi: float) -> dict[int, float]:
    x = max(lo, min(hi, x))
    a = math.floor(x * 2) / 2
    b = min(hi, a + 0.5)
    pa = table[str(a)] if str(a) in table else table[f"{a:.1f}"]
    pb = table[str(b)] if str(b) in table else table[f"{b:.1f}"]
    f = 0 if b == a else (x - a) / (b - a)
    keys = set(pa) | set(pb)
    return {int(k): (1 - f) * pa.get(k, 0.0) + f * pb.get(k, 0.0) for k in keys}


def margin_pmf(expected_home_margin: float, model: dict) -> dict[int, float]:
    """pmf of home margin when the market expects home to win by `expected_home_margin`.
    Outside the grid the nearest edge row is shifted."""
    lo, hi = SPREAD_GRID[0], SPREAD_GRID[-1]
    base = _interp(model["margin"], expected_home_margin, lo, hi)
    shift = round(expected_home_margin - max(lo, min(hi, expected_home_margin)))
    return {k + shift: v for k, v in base.items()} if shift else base


def total_pmf(expected_total: float, model: dict) -> dict[int, float]:
    lo, hi = TOTAL_GRID[0], TOTAL_GRID[-1]
    base = _interp(model["total"], expected_total, lo, hi)
    shift = round(expected_total - max(lo, min(hi, expected_total)))
    return {k + shift: v for k, v in base.items()} if shift else base


# ---------------------------------------------------------------- evaluation
def evaluate():
    """Train 2006-2021, test 2022+: for each test game and each sheet line within ±3 of the
    close, predict P(home covers the sheet line) from the close alone and score it."""
    sys.path.insert(0, ROOT)
    import beerpool as bp
    train = fit(range(2006, 2022))
    test = load(range(2022, 2030))
    res = {"parametric": [0.0, 0.0, 0], "empirical": [0.0, 0.0, 0]}
    tres = {"parametric": [0.0, 0.0, 0], "empirical": [0.0, 0.0, 0]}
    cal = {"parametric": {}, "empirical": {}}
    for g in test:
        s, m = g["s"], g["m"]
        par = bp.margin_pmf(s, "NFL")                 # bp: pmf of home margin with mean mu
        emp = margin_pmf(s, train)
        for off in (-3, -2.5, -2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2, 2.5, 3):
            line = -s + off                            # home line (negative = home gives points)
            y = 1 if m + line > 0 else 0               # push counts as loss
            for name, pmf in (("parametric", par), ("empirical", emp)):
                p = min(max(sum(v for k, v in pmf.items() if k + line > 0), 1e-6), 1 - 1e-6)
                r = res[name]
                r[0] += (p - y) ** 2
                r[1] += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                r[2] += 1
                b = round(p * 20) / 20
                c = cal[name].setdefault(b, [0, 0])
                c[0] += y
                c[1] += 1
        if g["T"] is not None and g["t"] is not None:
            T, t = g["T"], g["t"]
            ptot = bp.total_pmf(T, "NFL")
            etot = total_pmf(T, train)
            for off in (-3, -2, -1, -0.5, 0.5, 1, 2, 3):
                line = T + off
                y = 1 if t > line else 0
                for name, pmf in (("parametric", ptot), ("empirical", etot)):
                    p = min(max(sum(v for k, v in pmf.items() if k > line), 1e-6), 1 - 1e-6)
                    r = tres[name]
                    r[0] += (p - y) ** 2
                    r[1] += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                    r[2] += 1
    print(f"Out-of-sample: trained 2006-2021, tested on {len(test)} games 2022+")
    for title, rr in (("SPREADS (sheet line within ±3 of close)", res), ("TOTALS (within ±3)", tres)):
        print(f"  {title}")
        for name, (b, ll, n) in rr.items():
            print(f"    {name:<11} Brier {b / n:.5f}  log-loss {ll / n:.5f}  (n={n})")
    print("  key-number mass, home margin at spread -3 (home fav by 3):")
    par, emp = bp.margin_pmf(3, "NFL"), margin_pmf(3, train)
    for k in (1, 2, 3, 4, 6, 7, 10, 14):
        print(f"    margin {k:>2}: parametric {par.get(k, 0):.3f}  empirical {emp.get(k, 0):.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fit"
    if cmd == "fit":
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        m = fit()
        json.dump(m, open(OUT, "w"), separators=(",", ":"))
        print(f"wrote {OUT}: {m['meta']}")
    elif cmd == "eval":
        evaluate()
