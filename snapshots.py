#!/usr/bin/env python3
"""Odds snapshot logger + local database.

  python3 snapshots.py take            # fetch NFL + CFB from all books, save one snapshot
  python3 snapshots.py build-db        # (re)build data/odds.db from every saved snapshot
  python3 snapshots.py at "2026-11-07T11:30" [--league CFB]   # market as of a time (latest snapshot <= t)

Why: the backtest can only see opening and closing lines, and the close forms after the
pool's Saturday-noon deadline. Snapshots taken before the deadline (Thu sheet day, Fri
night, Sat 9:00 and 11:30 ET) let us measure what we could actually have known, and
later train the line-move model.

Storage: data/snapshots/YYYY-MM-DD/<UTC HHMM>_<league>.json.gz (committed by the cloud job;
~25 KB per snapshot). data/odds.db is derived from them. Mac fallback: ./schedule_mac.sh.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vi_parse  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
DB = os.path.join(ROOT, "data", "odds.db")
SOURCES = {"NFL": "https://www.vegasinsider.com/nfl/odds/las-vegas/",
           "CFB": "https://www.vegasinsider.com/college-football/odds/las-vegas/"}
BOOKS = vi_parse.BOOKS  # Open, bet365, BetMGM, DraftKings, Caesars, FanDuel, HardRock, Fanatics, Kalshi, Consensus


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")


def take(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    os.makedirs(os.path.join(SNAP_DIR, day), exist_ok=True)
    written = []
    for league, url in SOURCES.items():
        try:
            parsed = vi_parse.parse(fetch(url))
        except Exception as e:  # one league failing must not lose the other
            print(f"warning: {league}: {e}", file=sys.stderr)
            continue
        if not parsed["rows"]:
            print(f"warning: {league}: page parsed to 0 rows (layout change?)", file=sys.stderr)
            continue
        snap = {"taken_utc": now.isoformat(timespec="seconds"), "league": league,
                "source": url, "books": BOOKS, "rows": parsed["rows"]}
        path = os.path.join(SNAP_DIR, day, f"{now.strftime('%H%M')}_{league}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(snap, f, separators=(",", ":"))
        written.append(path)
        print(f"{league}: {len(parsed['rows'])} rows -> {os.path.relpath(path, ROOT)}")
    return written


SCHEMA = """
CREATE TABLE IF NOT EXISTS odds (
  taken_utc TEXT, league TEXT, market TEXT, rot INTEGER, team TEXT,
  book TEXT, line REAL, ou TEXT, price INTEGER
);
CREATE INDEX IF NOT EXISTS odds_t ON odds(league, taken_utc);
CREATE INDEX IF NOT EXISTS odds_team ON odds(team, market);
"""


def build_db() -> int:
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    n = 0
    for path in sorted(glob.glob(os.path.join(SNAP_DIR, "*", "*.json.gz"))):
        snap = json.load(gzip.open(path, "rt", encoding="utf-8"))
        books = snap["books"]
        rows = []
        for r in snap["rows"]:
            for i, c in enumerate(r["cells"]):
                if c and i < len(books):
                    rows.append((snap["taken_utc"], snap["league"], r["market"], r["rot"], r["team"],
                                 books[i], c.get("line"), c.get("ou"), c.get("price")))
        con.executemany("INSERT INTO odds VALUES (?,?,?,?,?,?,?,?,?)", rows)
        n += len(rows)
    con.commit()
    con.close()
    print(f"{DB}: {n} odds rows")
    return n


def market_at(t: str, league: str | None = None) -> dict:
    """Latest snapshot at or before t (ET wall-clock 'YYYY-MM-DDTHH:MM' or UTC ISO with Z)."""
    from zoneinfo import ZoneInfo
    ts = datetime.fromisoformat(t.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("America/New_York"))
    best = {}
    for path in sorted(glob.glob(os.path.join(SNAP_DIR, "*", "*.json.gz"))):
        lg = os.path.basename(path).split("_")[1].split(".")[0]
        if league and lg != league:
            continue
        snap = json.load(gzip.open(path, "rt", encoding="utf-8"))
        if datetime.fromisoformat(snap["taken_utc"]) <= ts:
            best[lg] = snap
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("take")
    sub.add_parser("build-db")
    p = sub.add_parser("at")
    p.add_argument("time")
    p.add_argument("--league")
    a = ap.parse_args()
    if a.cmd == "take":
        sys.exit(0 if take() else 1)
    if a.cmd == "build-db":
        build_db()
    if a.cmd == "at":
        for lg, s in market_at(a.time, a.league).items():
            print(lg, s["taken_utc"], len(s["rows"]), "rows")


if __name__ == "__main__":
    main()
