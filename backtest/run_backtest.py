#!/usr/bin/env python3
"""Backtest the pick engine against the commissioner's boards.

  python3 backtest/run_backtest.py [backtest/cache/results.json] [workbook.xlsx]

For every graded game the market is DraftKings' CLOSE (ESPN). Each side and total is
priced at the SHEET number with beerpool.py's model and graded at the sheet number
(push = loss). Reports:
  1. Calibration: model probability bucket -> actual cover rate.
  2. Number edge (sheet vs close) -> actual cover rate.
  3. Weekly card the engine would have built (no football notes, no movement tags)
     vs Bert's actual points and the pool, from the workbook's Pts tab.
Caveat: the close is after the Saturday-noon deadline and a single book, so this is an
upper bound on what the morning market would have shown.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import warnings
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import beerpool as bp  # noqa: E402

warnings.filterwarnings("ignore")


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", "and")).split())


def subseq(abbr: str, name: str) -> bool:
    it = iter(name.upper())
    return all(ch in it for ch in abbr.upper() if ch.isalpha())


def sheet_home_line(g: dict) -> float | None:
    """Sheet line from ESPN-home's perspective (negative = ESPN home favoured)."""
    fav, sp = g.get("fav"), g.get("spread")
    if fav is None or sp is None:
        return None
    if sp == 0:
        return 0.0
    f = norm(fav)
    home_names = set(g["espn_home_names"]) | {norm(g["home"]) if g["board_home_is_espn_home"] else norm(g["away"])}
    away_names = set(g["espn_away_names"]) | {norm(g["away"]) if g["board_home_is_espn_home"] else norm(g["home"])}
    if fav.upper() == g["espn_home"].upper() or f in home_names:
        return -sp
    if fav.upper() == g["espn_away"].upper() or f in away_names:
        return sp
    bh = g["home"] if g["board_home_is_espn_home"] else g["away"]
    ba = g["away"] if g["board_home_is_espn_home"] else g["home"]
    h, a = subseq(fav, bh), subseq(fav, ba)
    if h != a:
        return -sp if h else sp
    c = g.get("close", {}).get("home_spread")
    if c is not None and c != 0:
        return -sp if c < 0 else sp
    return None


def market(g: dict) -> dict | None:
    c = g.get("close") or {}
    if c.get("home_spread") is None or c.get("total") is None:
        return None
    hl = c["home_spread"]
    home, away = g["espn_home"], g["espn_away"]
    hp, ap = c.get("home_spread_odds") or -110, c.get("away_spread_odds") or -110
    m = {"fav": home if hl <= 0 else away, "spread": abs(hl),
         "fav_price": hp if hl <= 0 else ap, "dog_price": ap if hl <= 0 else hp,
         "total": c["total"], "over_price": c.get("over_odds") or -110,
         "under_price": c.get("under_odds") or -110}
    if c.get("open_home_spread") is not None:
        m["open_home"] = c["open_home_spread"]
    if c.get("open_total") is not None:
        m["open_total"] = c["open_total"]
    if abs(hl) <= 3.5 and c.get("ml_home") and c.get("ml_away"):
        m.update(ml_home=c["ml_home"], ml_away=c["ml_away"])
    return m


def board_for(games: list[dict]) -> dict:
    out = []
    for g in games:
        sh = sheet_home_line(g)
        mk = market(g)
        if sh is None or mk is None or g.get("total") is None:
            continue
        home, away = g["espn_home"], g["espn_away"]
        out.append({"num": g["num"], "league": g["league"], "away": away, "home": home,
                    "sheet_fav": home if sh <= 0 else away, "sheet_spread": abs(sh),
                    "sheet_total": g["total"], "market": mk})
    return {"week": "bt", "games": out}


def grade(c: bp.Candidate, g: dict) -> bool:
    margin = g["home_score"] - g["away_score"]  # ESPN home
    tot = g["home_score"] + g["away_score"]
    if c.side == "OVER":
        return tot > c.sheet_line
    if c.side == "UNDER":
        return tot < c.sheet_line
    if c.side == g["espn_home"]:
        return margin + c.sheet_line > 0
    return -margin + c.sheet_line > 0


def bucket(p: float) -> str:
    for lo in (0.56, 0.54, 0.53, 0.52, 0.51, 0.50):
        if p >= lo:
            return f">={lo:.2f}"
    return "<0.50"


def pool_points(xlsx: str) -> dict:
    """{week: {entrant: points}} from the Pts tab."""
    try:
        import openpyxl
    except ImportError:
        return {}
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Pts"]
    rows = list(ws.iter_rows(values_only=True))
    weeks = {i: str(v).replace("Week ", "") for i, v in enumerate(rows[0]) if v and str(v).startswith("Week")}
    out = defaultdict(dict)
    for r in rows[3:]:
        if not isinstance(r[0], int) or not r[1]:
            continue
        for i, wk in weeks.items():
            t = r[i + 5] if i + 5 < len(r) else None
            if isinstance(t, (int, float)) and any(isinstance(r[j], (int, float)) for j in range(i, i + 5)):
                out[wk][r[1]] = t
    return out


def main():
    res_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "cache", "results.json")
    xlsx = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "cache", "workbook.xlsx")
    games = [g for g in json.load(open(res_path)) if g.get("event_id") and g.get("status") == "STATUS_FINAL"]
    byweek = defaultdict(list)
    for g in games:
        byweek[(g["season"], g["week"])].append(g)

    cal = defaultdict(lambda: [0, 0])
    edge = defaultdict(lambda: [0, 0])
    kind = defaultdict(lambda: [0, 0])
    tagged = defaultdict(lambda: [0, 0])
    cards = []
    for (season, week), gs in sorted(byweek.items(), key=lambda k: (k[0][0], k[0][1].zfill(3))):
        board = board_for(gs)
        idx = {g["num"]: g for g in gs}
        cands, _ = bp.build_candidates(board, None, [])
        for c in cands:
            won = grade(c, idx[c.game])
            cal[bucket(c.p)][0] += won
            cal[bucket(c.p)][1] += 1
            e = c.number_edge
            ek = "+2 or more" if e >= 2 else f"{e:+g}" if e >= -2 else "-2 or less"
            if e >= -0.01:
                edge[ek][0] += won
                edge[ek][1] += 1
            if e > 0:
                t = "steam_against" if "steam_against" in c.tags else \
                    "big_move (with us)" if "big_move" in c.tags else "no move tag"
                tagged[t][0] += won
                tagged[t][1] += 1
                k = ("total" if c.side in ("OVER", "UNDER") else "spread") + " " + c.league
                kind[k][0] += won
                kind[k][1] += 1
        card, thin, _ = bp.build_card(cands)
        pts, rec = 0, []
        for i, c in enumerate(card, 1):
            w = grade(c, idx[c.game])
            pts += (5 if i <= 2 else 3) * w
            rec.append(f"{c.game} {c.label} {'W' if w else 'L'} ({c.p:.3f})")
        exp = sum((5 if i <= 2 else 3) * c.p for i, c in enumerate(card, 1))
        cards.append(dict(season=season, week=week, pts=pts, exp=exp, thin=thin, picks=rec,
                          n=len(board["games"])))

    print("== 1. CALIBRATION (every side/total, priced at the sheet number off the DK close) ==")
    print(f"{'model p':<8} {'n':>5} {'won':>6} {'actual':>7}")
    for k in [">=0.56", ">=0.54", ">=0.53", ">=0.52", ">=0.51", ">=0.50", "<0.50"]:
        w, n = cal[k]
        if n:
            print(f"{k:<8} {n:>5} {w:>6} {w / n:>7.3f}")

    print("\n== 2. NUMBER EDGE (points the sheet beats the close by, our side) ==")
    order = ["+0", "+0.5", "+1", "+1.5", "+2 or more"]
    for k in order:
        w, n = edge[k]
        if n:
            se = (0.25 / n) ** 0.5
            print(f"{k:<11} n={n:>4}  cover {w / n:.3f}  (±{1.96 * se:.3f})")
    print("   by type (any positive edge):")
    for k, (w, n) in sorted(kind.items()):
        print(f"   {k:<12} n={n:>4}  cover {w / n:.3f}")

    print("   by movement tag (any positive edge; open->close, so partly after the deadline):")
    for k, (w, n) in sorted(tagged.items()):
        print(f"   {k:<20} n={n:>4}  cover {w / n:.3f}")

    print("\n== 3. WEEKLY CARD (engine, no notes) vs the pool ==")
    pool = pool_points(xlsx)
    print(f"{'week':<10} {'games':>5} {'model':>6} {'exp':>5} {'Bert':>5} {'pool avg':>8} {'best':>5}")
    tot_m = tot_b = tot_avg = 0
    nw = 0
    for c in cards:
        wk = c["week"]
        p = pool.get(wk, {}) if c["season"] == 2026 else {}
        bert = p.get("Bert")
        avg = statistics.mean(p.values()) if p else None
        best = max(p.values()) if p else None
        print(f"{c['season']}-{wk:<5} {c['n']:>5} {c['pts']:>6} {c['exp']:>5.1f} "
              f"{bert if bert is not None else '-':>5} {f'{avg:.1f}' if avg else '-':>8} {best if best else '-':>5}"
              + ("  THIN" if c["thin"] else ""))
        if bert is not None:
            tot_m += c["pts"]
            tot_b += bert
            tot_avg += avg
            nw += 1
    if nw:
        print(f"\n2026 weeks with pool data: {nw}  model {tot_m}  Bert {tot_b}  pool avg {tot_avg:.1f}")
    allm = [c["pts"] for c in cards]
    print(f"All weeks: model avg {statistics.mean(allm):.2f}/wk, expected {statistics.mean(c['exp'] for c in cards):.2f}/wk "
          f"(break-even coin-flipping = 9.5)")
    print("\n== CARDS ==")
    for c in cards:
        print(f"{c['season']}-{c['week']}: {c['pts']} pts | " + " ; ".join(c["picks"]))


if __name__ == "__main__":
    main()
