#!/usr/bin/env python3
"""Backtest the pick engine against the commissioner's boards.

  python3 backtest/run_backtest.py [--results backtest/cache/results.json]
         [--pool 2025=BP-Week_21.xlsx --pool 2026=Beer_Pool_2026-27.xlsx]
         [--train 2025 --test 2026] [--cards]

The market is the CLOSE from ESPN (DraftKings, else ESPN BET). Every side and total is
priced at the SHEET number with beerpool.py and graded at the sheet number (push = loss).

Tuning is honest: TOTAL_SHRINK / SPREAD_SHRINK are fitted on the --train season only
(least Brier score), then everything is reported on both seasons, so the --test season
is out of sample. Variants compared:
  baseline  - engine as first merged (no shrink, big moves cap at 3 pts)
  tuned     - fitted shrinks, big moves toward us are a warning only
Caveat: the close is after the Saturday-noon deadline and one book, so this is an
upper bound on what the morning market would have shown.
"""
from __future__ import annotations

import argparse
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


# --------------------------------------------------------------------- data -> board
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
    bh = g["home"] if g["board_home_is_espn_home"] else g["away"]
    ba = g["away"] if g["board_home_is_espn_home"] else g["home"]
    if fav.upper() == g["espn_home"].upper() or f in set(g["espn_home_names"]) | {norm(bh)}:
        return -sp
    if fav.upper() == g["espn_away"].upper() or f in set(g["espn_away_names"]) | {norm(ba)}:
        return sp
    h, a = subseq(fav, bh), subseq(fav, ba)
    if h != a:
        return -sp if h else sp
    c = (g.get("close") or {}).get("home_spread")
    if c:
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
        sh, mk = sheet_home_line(g), market(g)
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


def pool_points(xlsx: str) -> dict:
    """{week: {entrant: points}} from a workbook's Pts tab."""
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Pts"]
    rows = list(ws.iter_rows(values_only=True))
    weeks = {i: str(v).replace("Week ", "") for i, v in enumerate(rows[0])
             if v and str(v).startswith("Week")}
    out = defaultdict(dict)
    for r in rows[3:]:
        if not isinstance(r[0], int) or not r[1]:
            continue
        for i, wk in weeks.items():
            t = r[i + 5] if i + 5 < len(r) else None
            if isinstance(t, (int, float)) and any(isinstance(r[j], (int, float)) for j in range(i, i + 5)):
                out[wk][r[1]] = t
    return out


# --------------------------------------------------------------------- engine settings
def configure(total_shrink: float, spread_shrink: float, big_move_caps: bool,
              huge_edge_p: float | None = None):
    bp.TOTAL_SHRINK, bp.SPREAD_SHRINK, bp.BIG_MOVE_CAPS = total_shrink, spread_shrink, big_move_caps
    bp.HUGE_EDGE_P = huge_edge_p


def candidates_by_week(weeks: dict) -> dict:
    out = {}
    for key, gs in weeks.items():
        idx = {g["num"]: g for g in gs}
        cands, _ = bp.build_candidates(board_for(gs), None, [])
        out[key] = [(c, grade(c, idx[c.game])) for c in cands]
    return out


def brier(pairs, kind: str) -> float:
    xs = [(c.p - w) ** 2 for c, w in pairs
          if (c.side in ("OVER", "UNDER")) == (kind == "total")]
    return statistics.mean(xs) if xs else float("nan")


def fit(weeks: dict) -> tuple[float, float]:
    grid = [round(x * 0.1, 1) for x in range(0, 16)]
    best = {}
    for kind in ("total", "spread"):
        scores = []
        for k in grid:
            configure(k if kind == "total" else 1.0, k if kind == "spread" else 1.0, True)
            pairs = [p for v in candidates_by_week(weeks).values() for p in v]
            scores.append((brier(pairs, kind), k))
        best[kind] = min(scores)[1]
        print(f"  fit {kind:<6}: " + "  ".join(f"{k:.1f}:{s:.4f}" for s, k in scores))
    return best["total"], best["spread"]


# --------------------------------------------------------------------- reports
def bucket(p: float) -> str:
    for lo in (0.56, 0.54, 0.53, 0.52, 0.51, 0.50):
        if p >= lo:
            return f">={lo:.2f}"
    return "<0.50"


def report_pricing(cbw: dict, title: str):
    cal, edge = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for pairs in cbw.values():
        for c, w in pairs:
            cal[bucket(c.p)][0] += w
            cal[bucket(c.p)][1] += 1
            e = c.number_edge
            if e > 0:
                typ = "total " if c.side in ("OVER", "UNDER") else "spread"
                eb = "3.5+" if e >= 3.5 else "2-3" if e >= 2 else "1-1.5" if e >= 1 else "0.5"
                for k in (f"{typ} {eb}", "any move tag: " + (
                        "steam_against" if "steam_against" in c.tags else
                        "big_move with us" if "big_move" in c.tags else "none")):
                    edge[k][0] += w
                    edge[k][1] += 1
    print(f"\n-- {title}: calibration (model p -> actual) --")
    for k in [">=0.56", ">=0.54", ">=0.53", ">=0.52", ">=0.51", ">=0.50", "<0.50"]:
        w, n = cal[k]
        if n:
            print(f"   {k:<7} n={n:>5}  actual {w / n:.3f}")
    print(f"-- {title}: positive number edge vs close --")
    for k in sorted(edge):
        w, n = edge[k]
        print(f"   {k:<30} n={n:>4}  cover {w / n:.3f}  (±{1.96 * (0.25 / n) ** 0.5:.3f})")


def run_cards(cbw: dict) -> dict:
    out = {}
    for key, pairs in cbw.items():
        res = dict((id(c), w) for c, w in pairs)
        card, thin, _ = bp.build_card([c for c, _ in pairs])
        pts = sum((5 if i <= 2 else 3) * res[id(c)] for i, c in enumerate(card, 1))
        exp = sum((5 if i <= 2 else 3) * c.p for i, c in enumerate(card, 1))
        wl = [res[id(c)] for c in card]
        five = sum(wl[:2]), sum(wl[2:])
        out[key] = dict(pts=pts, exp=exp, thin=thin, five=five,
                        picks=[f"{c.game} {c.label} {'W' if res[id(c)] else 'L'} {c.p:.3f}" for c in card])
    return out


def wkey(k):
    return (k[0], k[1].zfill(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "cache", "results.json"))
    ap.add_argument("--pool", action="append", default=[], help="SEASON=workbook.xlsx")
    ap.add_argument("--train", type=int, default=2025)
    ap.add_argument("--test", type=int, default=2026)
    ap.add_argument("--cards", action="store_true", help="print every weekly card")
    a = ap.parse_args()

    games = [g for g in json.load(open(a.results))
             if g.get("event_id") and g.get("status") == "STATUS_FINAL"]
    weeks = defaultdict(list)
    for g in games:
        weeks[(g["season"], g["week"])].append(g)
    train = {k: v for k, v in weeks.items() if k[0] == a.train}
    pool = {}
    for spec in a.pool:
        season, path = spec.split("=", 1)
        pool[int(season)] = pool_points(path)

    print(f"Games graded: {sum(len(v) for v in weeks.values())} "
          f"({', '.join(f'{s}: {sum(len(v) for k, v in weeks.items() if k[0] == s)}' for s in sorted({k[0] for k in weeks}))})")
    print(f"\n== FIT on {a.train} only (Brier score, lower is better) ==")
    ts, ss = fit(train)
    print(f"  -> TOTAL_SHRINK={ts}  SPREAD_SHRINK={ss}")

    variants = {"baseline": (1.0, 1.0, True), "tuned": (ts, ss, False),
                "tuned+cap": (ts, ss, False, 0.52)}
    cards = {}
    for name, cfg in variants.items():
        configure(*cfg)
        cbw = candidates_by_week(weeks)
        for season in sorted({k[0] for k in weeks}):
            sub = {k: v for k, v in cbw.items() if k[0] == season}
            tag = "train" if season == a.train else "TEST (out of sample)" if season == a.test else ""
            report_pricing(sub, f"{name} / {season} {tag}")
        cards[name] = run_cards(cbw)

    print("\n== WEEKLY CARDS: engine vs Bert vs pool ==")
    print(f"{'week':<9} {'games':>5} {'base':>5} {'tuned':>6} {'+cap':>5} {'Bert':>5} {'avg':>5} {'best':>5}")
    totals = defaultdict(lambda: defaultdict(float))
    for key in sorted(weeks, key=wkey):
        p = pool.get(key[0], {}).get(key[1], {})
        b, t = cards["baseline"][key], cards["tuned"][key]
        bert = p.get("Bert")
        avg = statistics.mean(p.values()) if p else None
        best = max(p.values()) if p else None
        print(f"{key[0]}-{key[1]:<4} {len(weeks[key]):>5} {b['pts']:>5} {t['pts']:>6} {cards['tuned+cap'][key]['pts']:>5} "
              f"{bert if bert is not None else '-':>5} {f'{avg:.1f}' if avg else '-':>5} {best if best else '-':>5}"
              + ("  thin" if t["thin"] else ""))
        s = totals[key[0]]
        s["weeks"] += 1
        s["base"] += b["pts"]
        s["tuned"] += t["pts"]
        s["cap"] += cards["tuned+cap"][key]["pts"]
        s["wins"] += sum(t["five"])
        s["five_w"] += t["five"][0]
        s["three_w"] += t["five"][1]
        s["picks"] += len(t["picks"])
        if bert is not None:
            s["pool_weeks"] += 1
            s["bert"] += bert
            s["avg"] += avg
            s["base_pw"] += b["pts"]
            s["tuned_pw"] += t["pts"]
            s["rank_tuned"] += 1 + sum(1 for v in p.values() if v > t["pts"])
            s["rank_bert"] += 1 + sum(1 for v in p.values() if v > bert)
            s["field"] = max(s["field"], len(p))
    print()
    for season, s in sorted(totals.items()):
        print(f"{season}: {int(s['weeks'])} weeks  baseline {s['base']:.0f} ({s['base'] / s['weeks']:.2f}/wk)  "
              f"tuned {s['tuned']:.0f} ({s['tuned'] / s['weeks']:.2f}/wk)  "
              f"tuned+cap {s['cap']:.0f}  |  tuned record {s['wins']:.0f}-{s['picks'] - s['wins']:.0f} "
              f"({s['wins'] / s['picks']:.1%})  5-pt {s['five_w']:.0f}/{2 * s['weeks']:.0f}  "
              f"3-pt {s['three_w']:.0f}/{s['picks'] - 2 * s['weeks']:.0f}")
        if s["pool_weeks"]:
            n = s["pool_weeks"]
            print(f"   weeks with pool data {n:.0f}: tuned {s['tuned_pw']:.0f}  baseline {s['base_pw']:.0f}  "
                  f"Bert {s['bert']:.0f}  pool avg {s['avg']:.1f}  | avg weekly rank (of ~{s['field']:.0f}): "
                  f"tuned {s['rank_tuned'] / n:.1f}  Bert {s['rank_bert'] / n:.1f}")
    if a.cards:
        print("\n== TUNED CARDS ==")
        for key in sorted(weeks, key=wkey):
            t = cards["tuned"][key]
            print(f"{key[0]}-{key[1]}: {t['pts']} | " + " ; ".join(t["picks"]))


if __name__ == "__main__":
    main()
