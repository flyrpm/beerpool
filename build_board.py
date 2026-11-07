#!/usr/bin/env python3
"""Build board.json for beerpool.py from the commissioner's PDF + live market.

  python3 build_board.py --pdf "BP Wk Niner.pdf" [--notes notes/2026-wk09.json]
                         [--cache DIR] [--offline] > board.json

- Sheet lines/totals/kickoffs come from the PDF (pdftotext -layout).
- Market = median of 7 sportsbooks on VegasInsider (bet365, BetMGM, DraftKings,
  Caesars, FanDuel, Hard Rock, Fanatics). Kalshi is excluded (leans dog).
  Prices are averaged at the median line. Opening line is kept for movement tags.
- Team abbreviations: the sheet's for the favourite, ESPN's for everyone else.
- A notes file layers the football handicap on top (adj / tags / thesis / env).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vi_parse  # noqa: E402

BOOK_IDX = range(1, 8)  # cells: 0=Open, 1..7 books, 8=Kalshi, 9=Consensus
VI_URL = "https://www.vegasinsider.com/{k}/odds/las-vegas/"
ESPN_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/"
            "college-football/scoreboard?dates={d}&groups=80&limit=300")
MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

NFL_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# --------------------------------------------------------------------- board
ROW = re.compile(
    r"^\s*(\d{1,3})\s+\w{3}, (\w{3}) (\d+), (\d{4})\s+(\d+):(\d+) ([AP]M)\s+(.+?)\s{2,}(?:at|vs)\s{2,}"
    r"(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+(PK|[+-]?\d+(?:\.\d)?)\s+(\d+(?:\.\d)?)\s*$")


def parse_board(text: str) -> list[dict]:
    games, league = [], "CFB"
    for ln in text.splitlines():
        if re.search(r"\bNFL\b\s*-", ln):
            league = "NFL"
        m = ROW.match(ln)
        if not m:
            continue
        num, mon, day, yr, hh, mm, ap, away, home, _tv, fav, line, total = m.groups()
        h = int(hh) % 12 + (12 if ap == "PM" else 0)
        ko = datetime(int(yr), MONTHS[mon], int(day), h, int(mm))
        games.append(dict(num=int(num), league=league, away_name=away.strip(),
                          home_name=home.strip(), kickoff=ko.isoformat(timespec="minutes"),
                          sheet_fav_abbr=fav, sheet_spread=abs(float(0 if line == "PK" else line)),
                          sheet_total=float(total)))
    return games


# --------------------------------------------------------------------- names
ALIAS = {
    "miami (oh)": "miami oh", "miami": "miami fl", "massachusetts": "umass",
    "san josé state": "san jose state", "hawai'i": "hawaii", "ul monroe": "louisiana monroe",
    "florida international": "fiu", "app state": "appalachian state",
}


def norm(s: str) -> str:
    s = s.lower().replace("&", "and").replace("é", "e").replace("’", "'")
    s = ALIAS.get(s, s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


EXPAND = {"st": "state", "n": "north", "s": "south", "w": "west", "e": "east",
          "ga": "georgia", "fla": "florida", "intl": "international", "so": "southern",
          "c": "central", "car": "carolina", "oh": "oh", "fl": "fl", "ul": "louisiana"}


def same_team(board_name: str, other: str, league: str) -> bool:
    b, o = norm(board_name), norm(other)
    if league == "NFL":
        return bool(o) and o.split()[-1] in b.split()
    if b == o or set(b.split()) == set(o.split()):
        return True
    return [EXPAND.get(t, t) for t in o.split()] == b.split()


# --------------------------------------------------------------------- fetch
def fetch(url: str, path: str | None, offline: bool) -> str:
    if offline:
        if not path or not os.path.exists(path):
            sys.exit(f"--offline but no cached copy of {url}")
        return open(path, encoding="utf-8", errors="replace").read()
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", errors="replace")
    if path:
        open(path, "w", encoding="utf-8").write(body)
    return body


def espn_abbrs(dates: set[str], cache: str | None, offline: bool) -> list[tuple[str, str]]:
    out = []
    for d in sorted(dates):
        path = os.path.join(cache, f"espn_{d}.json") if cache else None
        try:
            data = json.loads(fetch(ESPN_URL.format(d=d), path, offline))
        except Exception as e:  # abbreviations are cosmetic; never fatal
            print(f"warning: ESPN {d}: {e}", file=sys.stderr)
            continue
        for ev in data.get("events", []):
            for c in ev["competitions"][0]["competitors"]:
                t = c["team"]
                out.append((t.get("location", ""), t.get("abbreviation", "")))
    return out


# --------------------------------------------------------------------- market
def pairs(vi: dict, market: str):
    rows = [r for r in vi["rows"] if r["market"] == market]
    for a, h in zip(rows, rows[1:]):
        if a["rot"] % 2 == 1 and h["rot"] == a["rot"] + 1:
            yield a, h


def find(vi: dict, market: str, g: dict):
    for a, h in pairs(vi, market):
        if same_team(g["away_name"], a["team"], g["league"]) and \
           same_team(g["home_name"], h["team"], g["league"]):
            return a, h
    return None


def cell(row, i, key):
    c = row["cells"][i] if i < len(row["cells"]) else None
    return c.get(key) if c else None


def implied(a: float) -> float:
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def to_american(p: float) -> float:
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def at_median(lines, p1, p2):
    """Median line plus the average no-vig-ready prices of books sitting on it."""
    vals = [x for x in lines if x is not None]
    if not vals:
        return None
    med = statistics.median(vals)
    if med not in vals:  # between two lines: take the one nearer the middle book
        med = sorted(vals)[len(vals) // 2]
    idx = [i for i, x in enumerate(lines) if x == med and p1[i] and p2[i]]
    if not idx:
        return med, -110, -110, vals
    a = statistics.mean(implied(p1[i]) for i in idx)
    b = statistics.mean(implied(p2[i]) for i in idx)
    return med, to_american(a), to_american(b), vals


def market_for(g: dict, vi: dict) -> dict | None:
    mkt = {}
    sp = find(vi, "spread", g)
    if sp:
        a, h = sp
        hl = [cell(h, i, "line") for i in BOOK_IDX]
        hp = [cell(h, i, "price") for i in BOOK_IDX]
        ap = [cell(a, i, "price") for i in BOOK_IDX]
        r = at_median(hl, hp, ap)
        if r:
            med, php, pap, vals = r
            home_fav = med < 0 or (med == 0 and php < pap)
            mkt.update(fav="HOME" if home_fav else "AWAY", spread=abs(med),
                       fav_price=php if home_fav else pap, dog_price=pap if home_fav else php,
                       books={"spread": vals}, open_home=cell(h, 0, "line"))
    ml = find(vi, "moneyline", g)
    if ml and mkt.get("spread") is not None and mkt["spread"] <= 3.5:
        a, h = ml
        mh = [cell(h, i, "price") or cell(h, i, "line") for i in BOOK_IDX]
        ma = [cell(a, i, "price") or cell(a, i, "line") for i in BOOK_IDX]
        mh, ma = [x for x in mh if x], [x for x in ma if x]
        if mh and ma:
            mkt.update(ml_home=statistics.median(mh), ml_away=statistics.median(ma))
    tt = find(vi, "total", g)
    if tt:
        a, h = tt
        ol = [cell(a, i, "line") for i in BOOK_IDX]
        op = [cell(a, i, "price") for i in BOOK_IDX]
        up = [cell(h, i, "price") for i in BOOK_IDX]
        r = at_median(ol, op, up)
        if r:
            med, po, pu, vals = r
            mkt.update(total=med, over_price=po, under_price=pu,
                       open_total=cell(a, 0, "line"))
            mkt.setdefault("books", {})["total"] = vals
    return mkt or None


# --------------------------------------------------------------------- build
def abbr_for(name: str, league: str, espn: list[tuple[str, str]]) -> str:
    if league == "NFL":
        return NFL_ABBR.get(name, name.split()[-1].upper()[:3])
    for loc, ab in espn:
        if same_team(name, loc, "CFB"):
            return ab
    return re.sub(r"[^A-Z]", "", name.upper())[:6]


def build(pdf: str, notes: dict, cache: str | None, offline: bool) -> dict:
    text = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True,
                          text=True, check=True).stdout
    games = parse_board(text)
    if not games:
        sys.exit("no games parsed from the PDF; check the layout")
    vis = {}
    for lg, k in (("NFL", "nfl"), ("CFB", "college-football")):
        path = os.path.join(cache, f"vi_{k}.html") if cache else None
        vis[lg] = vi_parse.parse(fetch(VI_URL.format(k=k), path, offline))
    dates = {g["kickoff"][:10].replace("-", "") for g in games if g["league"] == "CFB"}
    espn = espn_abbrs(dates, cache, offline)

    sats = sorted({g["kickoff"][:10] for g in games
                   if datetime.fromisoformat(g["kickoff"]).weekday() == 5})
    default_lock = f"{sats[0]}T12:00" if sats else None

    out_games, unmatched = [], []
    for g in games:
        away = abbr_for(g["away_name"], g["league"], espn)
        home = abbr_for(g["home_name"], g["league"], espn)
        fav = g["sheet_fav_abbr"]
        # Which team is the sheet favourite? Prefer an exact abbreviation hit.
        if fav == home or (fav != away and fav[:3] == home[:3]):
            home = fav
        elif fav == away or fav[:3] == away[:3]:
            away = fav
        else:
            mkt0 = market_for(g, vis[g["league"]]) or {}
            if mkt0.get("fav") == "AWAY":
                away = fav
            else:
                home = fav
        rec = {"num": g["num"], "league": g["league"], "away": away, "home": home,
               "kickoff": g["kickoff"], "sheet_fav": fav, "sheet_spread": g["sheet_spread"],
               "sheet_total": g["sheet_total"],
               "names": f"{g['away_name']} at {g['home_name']}"}
        mkt = market_for(g, vis[g["league"]])
        if mkt:
            mkt["fav"] = home if mkt.get("fav") == "HOME" else away if mkt.get("fav") else None
            rec["market"] = mkt
        else:
            unmatched.append(g["num"])
        n = notes.get("games", {}).get(str(g["num"]))
        if n:
            rec["notes"] = n
        out_games.append(rec)
    if unmatched:
        print(f"warning: no market match for games {unmatched}", file=sys.stderr)
    return {"week": notes.get("week", "Week ?"), "default_lock": default_lock,
            "mega": notes.get("mega"), "as_of": datetime.now().isoformat(timespec="minutes"),
            "games": out_games}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--notes", help="weekly notes JSON (football layer)")
    ap.add_argument("--cache", default="cache", help="where fetched pages are saved")
    ap.add_argument("--offline", action="store_true", help="reuse cached pages, no fetch")
    a = ap.parse_args()
    notes = json.load(open(a.notes)) if a.notes else {}
    if a.cache:
        os.makedirs(a.cache, exist_ok=True)
    json.dump(build(a.pdf, notes, a.cache, a.offline), sys.stdout, indent=1)


if __name__ == "__main__":
    main()
