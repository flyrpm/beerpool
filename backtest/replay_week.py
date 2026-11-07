#!/usr/bin/env python3
"""Replay one past week: what the engine would have picked, graded, next to Bert's card.

  python3 backtest/replay_week.py --season 2026 --week 5 [--cap]
         [--workbook backtest/cache/workbook.xlsx]

Uses backtest/cache/results.json (run extract_boards.py + fetch_results.py first).
Shows the top college and NFL candidates, the engine's card with results, Bert's actual
picks and the pool's scores that week. --cap turns on the huge-edge cap (HUGE_EDGE_P=0.52).
Same caveat as the backtest: the market is the CLOSE, after the Saturday-noon deadline.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import beerpool as bp  # noqa: E402
import run_backtest as rb  # noqa: E402

warnings.filterwarnings("ignore")


def bert_card(workbook: str, week: str) -> list[str]:
    import openpyxl
    rows = list(openpyxl.load_workbook(workbook, data_only=True)["Bert"].iter_rows(values_only=True))
    for i, r in enumerate(rows):
        if r[0] == "BERT" and str(r[1]).upper() == f"WEEK {week.upper()}":
            return [f"{r2[3]}  {r2[4]} {r2[5]}" for r2 in rows[i + 1:i + 6] if r2[3]]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", required=True)
    ap.add_argument("--results", default=os.path.join(HERE, "cache", "results.json"))
    ap.add_argument("--workbook", help="that season's standings workbook (for Bert + pool)")
    ap.add_argument("--cap", action="store_true")
    a = ap.parse_args()
    cfg = bp.Config.production()
    if a.cap:
        cfg = cfg.with_(huge_edge_p=0.52)

    games = [g for g in json.load(open(a.results))
             if g.get("event_id") and g.get("status") == "STATUS_FINAL"
             and g["season"] == a.season and g["week"] == a.week]
    if not games:
        sys.exit("no graded games for that season/week")
    idx = {g["num"]: g for g in games}
    board = rb.board_for(games)
    cands, _ = bp.build_candidates(board, None, [], cfg)
    res = {id(c): rb.grade(c, idx[c.game]) for c in cands}

    def final(c):
        g = idx[c.game]
        return f"{g['espn_away']} {g['away_score']}-{g['home_score']} {g['espn_home']}"

    def mkt(c):
        return bp.fmt_line(c.market_line, c.side not in ("OVER", "UNDER"))

    n_cfb = sum(1 for g in board["games"] if g["league"] == "CFB")
    print(f"engine: {cfg.describe()}")
    print(f"{a.season} Week {a.week}: {len(board['games'])} games priced ({n_cfb} college, "
          f"{len(board['games']) - n_cfb} NFL)")
    for lg in ("CFB", "NFL"):
        print(f"-- top {lg} --")
        for c in sorted((c for c in cands if c.league == lg), key=lambda c: c.p, reverse=True)[:5]:
            print(f"  {c.p:.3f} {c.game:>3} {c.label:<26} close {mkt(c):<6} edge {c.number_edge:+g} "
                  f"[{','.join(sorted(c.tags)) or '-'}] {final(c):<20} {'WIN' if res[id(c)] else 'loss'}")
    card, thin, _ = bp.build_card(cands, cfg=cfg)
    pts = 0
    print("-- ENGINE CARD --" + ("  (thin board)" if thin else ""))
    for i, c in enumerate(card, 1):
        v = 5 if i <= 2 else 3
        pts += v * res[id(c)]
        print(f"  {i}. {c.game} {c.label:<26} p={c.p:.3f} close {mkt(c):<6} {final(c):<20} "
              f"{'W' if res[id(c)] else 'L'} {v * res[id(c)]}")
    print(f"  TOTAL {pts}/19 (expected {sum((5 if i <= 2 else 3) * c.p for i, c in enumerate(card, 1)):.1f})")
    if a.workbook:
        print("-- BERT'S ACTUAL --")
        for line in bert_card(a.workbook, a.week):
            print("  " + line)
        p = rb.pool_points(a.workbook).get(a.week, {})
        if p:
            print(f"  Bert {p.get('Bert')} | pool avg {statistics.mean(p.values()):.1f} | best {max(p.values())}")


if __name__ == "__main__":
    main()
