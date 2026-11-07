#!/usr/bin/env python3
"""Pool standings from the commissioner's workbook, as JSON (the standings "API").

  python3 standings.py Beer_Pool_2026-27.xlsx --season 2026 [--out data/lake/api/]

Writes two files (and prints a summary):
  weekly_points.json  one row per entrant per graded week:
      {season, entrant, week, week_order, points, wins, picks, p1..p5}
  standings.json      one row per entrant, season to date:
      {season, rank, entrant, points, wins, losses, picks, win_pct, weeks,
       last_week, last_week_points, gap_to_leader, avg_per_week}
Source: the workbook's "Pts" tab (points per pick slot: 5,5,3,3,3; a 0 is a loss, and
pushes count as losses). A week counts once every slot has a number and at least one entrant scored
(the workbook pre-fills future weeks with zeros).
"""
from __future__ import annotations

import argparse
import json
import os
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")


def week_order(w: str) -> int:
    return 0 if w == "A" else int(w)


def weekly_points(xlsx: str, season: int) -> list[dict]:
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Pts"]
    rows = list(ws.iter_rows(values_only=True))
    weeks = {i: str(v).replace("Week ", "").strip() for i, v in enumerate(rows[0])
             if v and str(v).startswith("Week")}
    out = []
    for r in rows[3:]:
        if not isinstance(r[0], int) or not r[1]:
            continue
        for i, wk in weeks.items():
            slots = [r[j] if j < len(r) else None for j in range(i, i + 5)]
            if not all(isinstance(x, (int, float)) for x in slots):
                continue
            pts = [int(x) for x in slots]
            out.append({"season": season, "entrant": str(r[1]).strip(), "week": wk,
                        "week_order": week_order(wk), "points": sum(pts),
                        "wins": sum(1 for x in pts if x > 0), "picks": 5,
                        **{f"p{k + 1}": pts[k] for k in range(5)}})
    # The workbook pre-fills future weeks with zeros: a week counts only once someone scored.
    played = {w["week"] for w in out if w["points"] > 0}
    out = [w for w in out if w["week"] in played]
    return sorted(out, key=lambda x: (x["week_order"], x["entrant"]))


def standings(weekly: list[dict]) -> list[dict]:
    by = {}
    for w in weekly:
        s = by.setdefault(w["entrant"], {"entrant": w["entrant"], "season": w["season"], "points": 0,
                                         "wins": 0, "picks": 0, "weeks": 0, "last": (-1, None, 0)})
        s["points"] += w["points"]
        s["wins"] += w["wins"]
        s["picks"] += w["picks"]
        s["weeks"] += 1
        if w["week_order"] > s["last"][0]:
            s["last"] = (w["week_order"], w["week"], w["points"])
    table = sorted(by.values(), key=lambda s: (-s["points"], -s["wins"], s["entrant"]))
    leader = table[0]["points"] if table else 0
    out, prev, rank = [], None, 0
    for i, s in enumerate(table, 1):
        if s["points"] != prev:
            rank, prev = i, s["points"]
        out.append({"season": s["season"], "rank": rank, "entrant": s["entrant"],
                    "points": s["points"], "wins": s["wins"], "losses": s["picks"] - s["wins"],
                    "picks": s["picks"], "win_pct": round(s["wins"] / s["picks"], 4) if s["picks"] else None,
                    "weeks": s["weeks"], "last_week": s["last"][1], "last_week_points": s["last"][2],
                    "gap_to_leader": leader - s["points"],
                    "avg_per_week": round(s["points"] / s["weeks"], 2) if s["weeks"] else None})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", default="data/api")
    a = ap.parse_args()
    weekly = weekly_points(a.xlsx, a.season)
    table = standings(weekly)
    os.makedirs(a.out, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, rows in (("weekly_points.json", weekly), ("standings.json", table)):
        with open(os.path.join(a.out, name), "w") as f:
            json.dump({"generated_utc": stamp, "source": os.path.basename(a.xlsx), "rows": rows}, f, indent=1)
    weeks = sorted({w["week"] for w in weekly}, key=week_order)
    print(f"{len(table)} entrants, weeks {weeks[0]}-{weeks[-1]} ({len(weeks)}), {len(weekly)} entrant-weeks -> {a.out}")
    for s in table[:5]:
        print(f"  {s['rank']:>2}. {s['entrant']:<10} {s['points']:>4} pts  {s['wins']}-{s['losses']}  gap {s['gap_to_leader']}")
    bert = next((s for s in table if s["entrant"] == "Bert"), None)
    if bert:
        print(f"  Bert: rank {bert['rank']}, {bert['points']} pts, {bert['wins']}-{bert['losses']}, gap {bert['gap_to_leader']}")


if __name__ == "__main__":
    main()
