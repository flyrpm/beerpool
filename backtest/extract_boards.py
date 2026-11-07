#!/usr/bin/env python3
"""Pull every week's board out of the commissioner's standings workbook.

  python3 backtest/extract_boards.py Beer_Pool_2026-27.xlsx > backtest/boards.json

Handles the three layouts the workbook uses:
  A) Wk A-2 (2026):  num | away | "@/v" + home | time | "Line: ABBR -x"  (+ "O/U: x" row)
  B) Wk 3-9 (2026):  num | date | time | away | at | home | tv | "ABBR -x" | total
  C) Wk 10-21 (2025): num | date/time | favourite | -spread | underdog | total  ("at" marks home)
Output rows: week, season, num, date (ET), away, home, fav (abbr or name), spread, total.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from datetime import date, datetime

import openpyxl

warnings.filterwarnings("ignore")

RANK = re.compile(r"^\s*(?:No\.\s*\d{1,2}\s+|\d{1,2}(?=[A-Z]))")


def clean(name) -> str:
    s = str(name).replace("\xa0", " ").strip()
    s = re.sub(r"^\s*(@|v|vs\.?|at)\s+", "", s)
    return RANK.sub("", s).strip()


def to_date(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        m = re.search(r"(\w+) (\d{1,2}), (\d{4})", v)
        if m:
            try:
                return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat()
            except ValueError:
                return datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat()
    return None


def parse_line(s):
    m = re.search(r"([A-Z][A-Z&\-\.]*)\s+(-?\d+(?:\.\d)?|PK)", str(s))
    if not m:
        return None, None
    return m.group(1), abs(float(0 if m.group(2) == "PK" else m.group(2)))


def layout_a(ws, week):
    out, cur = [], None
    rows = list(ws.iter_rows(values_only=True))
    for i, r in enumerate(rows):
        if isinstance(r[0], (datetime, date)):
            cur = to_date(r[0])
            continue
        if not isinstance(r[0], int) or not isinstance(r[1], str) or not isinstance(r[2], str):
            continue
        fav, sp = parse_line(r[4])
        tot = None
        if i + 1 < len(rows) and rows[i + 1][4] and "O/U" in str(rows[i + 1][4]):
            m = re.search(r"(\d+(?:\.\d)?)", str(rows[i + 1][4]))
            tot = float(m.group(1)) if m else None
        out.append(dict(week=week, num=r[0], date=cur, away=clean(r[1]), home=clean(r[2]),
                        neutral=" v " in str(r[2]).replace("\xa0", " "),
                        fav=fav, spread=sp, total=tot))
    return out


def layout_b(ws, week):
    out = []
    for r in ws.iter_rows(values_only=True):
        if not isinstance(r[0], int) or len(r) < 9 or not isinstance(r[3], str) \
                or not isinstance(r[1], (datetime, date, str)) or isinstance(r[1], str) and not to_date(r[1]):
            continue
        fav, sp = parse_line(r[7])
        out.append(dict(week=week, num=r[0], date=to_date(r[1]), away=clean(r[3]),
                        home=clean(r[5]), neutral=str(r[4]).strip().lower().startswith("v"),
                        fav=fav, spread=sp,
                        total=float(r[8]) if isinstance(r[8], (int, float)) else None))
    return out


def layout_c(ws, week):
    out = []
    for r in ws.iter_rows(values_only=True):
        if not isinstance(r[0], int) or not r[2] or not r[4]:
            continue
        fav_raw, dog_raw = str(r[2]), str(r[4])
        fav, dog = clean(fav_raw), clean(dog_raw)
        fav_home = fav_raw.strip().lower().startswith("at ")
        away, home = (dog, fav) if fav_home else (fav, dog)
        if not fav_home and not dog_raw.strip().lower().startswith("at "):
            away, home = fav, dog  # neutral site; order is arbitrary
        out.append(dict(week=week, num=r[0], date=to_date(r[1]), away=away, home=home,
                        neutral=False, fav=fav,
                        spread=abs(float(r[3])) if isinstance(r[3], (int, float)) else None,
                        total=float(r[5]) if isinstance(r[5], (int, float)) else None))
    return out


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    games = []
    for ws in wb.worksheets:
        m = re.match(r"^Wk (\w+)", ws.title)
        if not m:
            continue
        week = m.group(1)
        first = [c for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
        if first[0] == "Game" and len(first) >= 6 and first[2] == "Favorite":
            rows, season = layout_c(ws, week), 2025
        else:  # 2026 tabs can mix layouts A and B (Week 2 does): take both, row-wise
            seen, rows, season = set(), [], 2026
            for g in layout_a(ws, week) + layout_b(ws, week):
                if g["num"] not in seen:
                    seen.add(g["num"])
                    rows.append(g)
        for g in rows:
            g["season"] = season
            g["draft"] = "DRAFT" in ws.title
        games += rows
    json.dump(games, sys.stdout, indent=0)


if __name__ == "__main__":
    main(sys.argv[1])
