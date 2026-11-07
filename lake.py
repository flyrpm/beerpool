#!/usr/bin/env python3
"""BeerPool data lake: immutable raw files + a rebuildable SQLite query layer.

  python3 lake.py init                                   # check out the data-lake branch at data/lake
  python3 lake.py add-sheet BOARD.pdf --season 2026 --week 9 [--message-id ID --received ISO]
  python3 lake.py add-workbook Beer_Pool_2026-27.xlsx --season 2026
  python3 lake.py add-file PATH --kind ledger|grades|evaluation|other
  python3 lake.py build                                  # (re)build data/lake.db from everything
  python3 lake.py sql "select * from picks limit 5"
  python3 lake.py sync                                   # commit + push the data-lake branch

Layout
  Raw layer (git branch `data-lake`, private repo, checked out at data/lake/, append-only):
    raw/sheets/<season>-wk<NN>/<sha12>_<name>.pdf  + .meta.json (sha256, source, received)
    raw/workbooks/<season>/<sha12>_<name>.xlsx     + .meta.json
    raw/context/<date>/<league>_<event>.json       (context.py writes here, with fetch time)
    ledger/{predictions,grades,evaluation}/...     (the frozen prospective ledger's private files)
  Odds snapshots stay in data/snapshots/ on main (the cloud runner commits them there).
  Query layer: data/lake.db (SQLite, git-ignored), rebuilt from the raw layer at any time:
    teams, sheet_games, odds, results, picks, context, files
Nothing in the raw layer is ever edited: add-* refuses to overwrite and records sha256.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
LAKE = os.path.join(ROOT, "data", "lake")
DB = os.path.join(ROOT, "data", "lake.db")
SNAPS = os.path.join(ROOT, "data", "snapshots")
BRANCH = "data-lake"


def sh(*args, cwd=ROOT, check=True) -> str:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True).stdout.strip()


def load_json(path: str):
    with open(path) as f:
        return json.load(f)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ raw layer
def init() -> str:
    if os.path.isdir(os.path.join(LAKE, ".git")) or os.path.isfile(os.path.join(LAKE, ".git")):
        return f"lake already at {LAKE}"
    sh("git", "fetch", "origin", check=False)
    remote = sh("git", "ls-remote", "--heads", "origin", BRANCH, check=False)
    if remote:
        sh("git", "worktree", "add", LAKE, BRANCH)
        return f"checked out existing {BRANCH} at {LAKE}"
    sh("git", "worktree", "add", "--detach", LAKE)
    sh("git", "checkout", "--orphan", BRANCH, cwd=LAKE)
    sh("git", "rm", "-rf", "--quiet", ".", cwd=LAKE, check=False)
    for d in ("raw/sheets", "raw/workbooks", "raw/context", "ledger"):
        os.makedirs(os.path.join(LAKE, d), exist_ok=True)
    with open(os.path.join(LAKE, "README.md"), "w") as f:
        f.write("# BeerPool data lake (private)\n\nRaw, append-only inputs and private ledger files. "
                "Managed by `lake.py` on main; see its docstring for the layout.\n")
    sh("git", "add", "README.md", cwd=LAKE)
    sh("git", "commit", "-q", "-m", "Initialize data lake", cwd=LAKE)
    return f"created orphan branch {BRANCH} at {LAKE} (run `lake.py sync` to push)"


def _add(src: str, dest_dir: str, meta: dict) -> str:
    if not os.path.isdir(LAKE):
        sys.exit("no lake checked out: run `python3 lake.py init` first")
    digest = sha256(src)
    os.makedirs(dest_dir, exist_ok=True)
    for existing in glob.glob(os.path.join(dest_dir, "*.meta.json")):
        if load_json(existing).get("sha256") == digest:
            return f"already stored: {os.path.relpath(existing[:-10], LAKE)}"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(src))
    dest = os.path.join(dest_dir, f"{digest[:12]}_{name}")
    if os.path.exists(dest):
        raise FileExistsError(dest)
    shutil.copyfile(src, dest)
    meta = dict(meta, sha256=digest, bytes=os.path.getsize(src), original_name=os.path.basename(src),
                stored_utc=datetime.now(timezone.utc).isoformat())
    with open(dest + ".meta.json", "x") as f:
        json.dump(meta, f, indent=1)
    return f"stored {os.path.relpath(dest, LAKE)}"


def add_sheet(pdf: str, season: int, week: str, message_id=None, received=None) -> str:
    return _add(pdf, os.path.join(LAKE, "raw", "sheets", f"{season}-wk{str(week).zfill(2)}"),
                {"kind": "sheet", "season": season, "week": str(week),
                 "gmail_message_id": message_id, "received": received})


def add_workbook(xlsx: str, season: int) -> str:
    return _add(xlsx, os.path.join(LAKE, "raw", "workbooks", str(season)),
                {"kind": "workbook", "season": season})


def add_file(path: str, kind: str) -> str:
    sub = {"ledger": "ledger/predictions", "grades": "ledger/grades",
           "evaluation": "ledger/evaluation"}.get(kind, f"raw/{kind}")
    return _add(path, os.path.join(LAKE, sub), {"kind": kind})


def sync(message: str = "Data lake update") -> str:
    sh("git", "add", "-A", cwd=LAKE)
    if not sh("git", "status", "--porcelain", cwd=LAKE):
        return "nothing to commit"
    sh("git", "commit", "-q", "-m", message, cwd=LAKE)
    out = subprocess.run(["git", "push", "-u", "origin", BRANCH], cwd=LAKE,
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip())
    return f"pushed {sh('git', 'rev-parse', '--short', 'HEAD', cwd=LAKE)} to {BRANCH}"


# ------------------------------------------------------------------ query layer
SCHEMA = """
CREATE TABLE files (path TEXT PRIMARY KEY, kind TEXT, sha256 TEXT, season INTEGER, week TEXT, meta TEXT);
CREATE TABLE teams (league TEXT, id TEXT, abbr TEXT, location TEXT, name TEXT, display TEXT, tier TEXT,
                    PRIMARY KEY (league, id));
CREATE TABLE sheet_games (season INTEGER, week TEXT, num INTEGER, league TEXT, away TEXT, home TEXT,
                          kickoff TEXT, fav TEXT, spread REAL, total REAL, sheet_sha256 TEXT,
                          PRIMARY KEY (season, week, num));
CREATE TABLE odds (taken_utc TEXT, received_utc TEXT, league TEXT, market TEXT, rot INTEGER,
                   team TEXT, book TEXT, line REAL, ou TEXT, price INTEGER, snapshot TEXT);
CREATE INDEX odds_team ON odds(team, market, taken_utc);
CREATE TABLE results (season INTEGER, week TEXT, num INTEGER, league TEXT, event_id TEXT,
                      away TEXT, home TEXT, away_score INTEGER, home_score INTEGER,
                      close_home_spread REAL, close_total REAL, open_home_spread REAL, open_total REAL,
                      provider TEXT, PRIMARY KEY (season, week, num));
CREATE TABLE picks (run TEXT, slot INTEGER, points INTEGER, game INTEGER, label TEXT, p REAL,
                    PRIMARY KEY (run, slot));
CREATE TABLE context (fetched_utc TEXT, league TEXT, event_id TEXT, fpi_home_pct REAL,
                      indoor INTEGER, temperature REAL, gust REAL, precip REAL, n_injuries INTEGER,
                      PRIMARY KEY (event_id, fetched_utc));
"""


def build(db: str = DB, lake: str = LAKE, snaps: str = SNAPS, root: str = ROOT) -> dict:
    sys.path.insert(0, root)
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    counts = {}

    # teams
    tp = os.path.join(root, "models", "teams.json")
    if os.path.exists(tp):
        for league, ts in load_json(tp).items():
            con.executemany("INSERT INTO teams VALUES (?,?,?,?,?,?,?)",
                            [(league, i, t.get("abbreviation"), t.get("location"), t.get("name"),
                              t.get("displayName"), t.get("tier", "pro" if league == "NFL" else ""))
                             for i, t in ts.items()])

    # raw files + sheets
    for meta_path in sorted(glob.glob(os.path.join(lake, "**", "*.meta.json"), recursive=True)):
        meta = load_json(meta_path)
        path = os.path.relpath(meta_path[:-10], lake)
        con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                    (path, meta.get("kind"), meta.get("sha256"), meta.get("season"),
                     meta.get("week"), json.dumps(meta)))
        if meta.get("kind") == "sheet" and path.endswith(".pdf"):
            import build_board
            text = subprocess.run(["pdftotext", "-layout", meta_path[:-10], "-"],
                                  capture_output=True, text=True).stdout
            for g in build_board.parse_board(text):
                con.execute("INSERT OR REPLACE INTO sheet_games VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (meta["season"], meta["week"], g["num"], g["league"], g["away_name"],
                             g["home_name"], g["kickoff"], g["sheet_fav_abbr"], g["sheet_spread"],
                             g["sheet_total"], meta["sha256"]))

    # odds snapshots (main branch)
    for path in sorted(glob.glob(os.path.join(snaps, "*", "*.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
        books, rows = snap["books"], []
        for r in snap["rows"]:
            for i, c in enumerate(r["cells"]):
                if c and i < len(books):
                    rows.append((snap["taken_utc"], snap.get("received_utc"), snap["league"],
                                 r["market"], r["rot"], r["team"], books[i], c.get("line"),
                                 c.get("ou"), c.get("price"), os.path.relpath(path, root)))
        con.executemany("INSERT INTO odds VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    # graded results (backtest cache, if present)
    rp = os.path.join(root, "backtest", "cache", "results.json")
    if os.path.exists(rp):
        for g in load_json(rp):
            if not g.get("event_id"):
                continue
            c = g.get("close") or {}
            con.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (g["season"], g["week"], g["num"], g.get("league"), g["event_id"],
                         g.get("espn_away"), g.get("espn_home"), g.get("away_score"),
                         g.get("home_score"), c.get("home_spread"), c.get("total"),
                         c.get("open_home_spread"), c.get("open_total"), c.get("provider")))

    # archived live cards
    pick_re = re.compile(r"^\s*Pick (\d) \((\d)\) (\d+) (.+?)\s+p=([\d.]+)")
    for card in sorted(glob.glob(os.path.join(root, "runs", "*", "card.txt"))):
        run = os.path.basename(os.path.dirname(card))
        in_card = False
        with open(card) as fh:
            lines = fh.readlines()
        for line in lines:
            if line.startswith("== CARD"):
                in_card = True
                continue
            if in_card and line.startswith("=="):
                break
            m = pick_re.match(line) if in_card else None
            if m:
                con.execute("INSERT OR REPLACE INTO picks VALUES (?,?,?,?,?,?)",
                            (run, int(m[1]), int(m[2]), int(m[3]), m[4].strip(), float(m[5])))

    # context pulls
    for path in sorted(glob.glob(os.path.join(lake, "raw", "context", "*", "*.json"))):
        doc = load_json(path)
        d = doc.get("data", {})
        league, eid = os.path.basename(path)[:-5].split("_", 1)
        gi = d.get("gameInfo") or {}
        w = gi.get("weather") or {}
        try:
            fpi = float(d["predictor"]["homeTeam"]["gameProjection"])
        except (KeyError, TypeError, ValueError):
            fpi = None
        con.execute("INSERT OR REPLACE INTO context VALUES (?,?,?,?,?,?,?,?,?)",
                    (doc.get("fetched_utc"), league, eid, fpi,
                     int(bool((gi.get("venue") or {}).get("indoor"))), w.get("temperature"),
                     w.get("gust"), w.get("precipitation"),
                     sum(len(t.get("injuries") or []) for t in d.get("injuries") or [])))

    con.commit()
    for t in ("files", "teams", "sheet_games", "odds", "results", "picks", "context"):
        counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    con.close()
    return counts


def sql(query: str, db: str = DB) -> list[tuple]:
    con = sqlite3.connect(db)
    cur = con.execute(query)
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchall()
    con.close()
    return [tuple(cols)] + rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("add-sheet")
    p.add_argument("pdf")
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--week", required=True)
    p.add_argument("--message-id")
    p.add_argument("--received")
    p = sub.add_parser("add-workbook")
    p.add_argument("xlsx")
    p.add_argument("--season", type=int, required=True)
    p = sub.add_parser("add-file")
    p.add_argument("path")
    p.add_argument("--kind", required=True)
    sub.add_parser("build")
    p = sub.add_parser("sql")
    p.add_argument("query")
    p = sub.add_parser("sync")
    p.add_argument("-m", "--message", default="Data lake update")
    a = ap.parse_args()
    if a.cmd == "init":
        print(init())
    elif a.cmd == "add-sheet":
        print(add_sheet(a.pdf, a.season, a.week, a.message_id, a.received))
    elif a.cmd == "add-workbook":
        print(add_workbook(a.xlsx, a.season))
    elif a.cmd == "add-file":
        print(add_file(a.path, a.kind))
    elif a.cmd == "build":
        print(json.dumps(build(), indent=1))
    elif a.cmd == "sql":
        for row in sql(a.query):
            print(" | ".join("" if v is None else str(v) for v in row))
    elif a.cmd == "sync":
        print(sync(a.message))


if __name__ == "__main__":
    main()
