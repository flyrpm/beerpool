#!/usr/bin/env python3
"""Match board games to ESPN events; pull final scores and the DraftKings close.

  python3 backtest/fetch_results.py backtest/cache/boards.json > backtest/cache/results.json

Cached under backtest/cache/espn/ so re-runs are free. ESPN's close is a single book
(DraftKings) taken at kickoff, i.e. AFTER the pool's Saturday-noon deadline: a backtest
priced off it is a slightly optimistic stand-in for the morning market.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/"
LEAGUE_PATH = {"NFL": "nfl", "CFB": "college-football"}
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "espn")


def get(url: str, key: str):
    path = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode())
            tmp = f"{path}.{os.getpid()}.{id(data)}.tmp"
            json.dump(data, open(tmp, "w"))
            os.replace(tmp, path)  # atomic: readers never see a half-written file
            return data
        except Exception as e:  # transient network errors: back off and retry
            if attempt == 3:
                print(f"warning: {url}: {e}", file=sys.stderr)
                return {}
            time.sleep(2 ** attempt)


def scoreboard(league: str, d: str):
    q = f"dates={d.replace('-', '')}" + ("&groups=80&limit=300" if league == "CFB" else "")
    return get(f"{BASE}{LEAGUE_PATH[league]}/scoreboard?{q}", f"sb_{league}_{d}")


def norm(s: str) -> str:
    s = s.lower().replace("&", "and").replace("é", "e").replace("’", "'").replace("ʻ", "'")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def names(team: dict, league: str) -> set[str]:
    out = {norm(team.get(k, "")) for k in ("location", "displayName", "shortDisplayName")}
    if league == "NFL":
        out.add(norm(team.get("name", "")))
    out.add(norm(team.get("abbreviation", "")))
    return {x for x in out if x}


LONG_FORM = [("north carolina state", "nc state"), ("connecticut", "uconn"),
             ("louisiana lafayette", "louisiana"), ("louisiana monroe", "ul monroe"),
             ("appalachian state", "app state"), ("hawaii", "hawai i"),
             ("southern methodist", "smu"), ("central florida", "ucf"),
             ("massachusetts", "umass"), ("florida international", "fiu"),
             ("sam houston state", "sam houston"), ("miami fl", "miami"),
             ("san jose state", "san jose state")]


def team_hit(board_name: str, team: dict, league: str) -> bool:
    b = norm(board_name)
    if b in names(team, league):
        return True
    if league == "CFB":
        for a, z in LONG_FORM:
            if b == a or b.startswith(a + " "):
                b = z + b[len(a):]
                break
        if b in names(team, league):
            return True
        # Last season's sheet: "<location> <nickname>", nickname spelled its own way
        # ("UNLV Runnin' Rebels"). Accept location + any nickname of 1-3 words.
        loc = norm(team.get("location", ""))
        rest = b[len(loc) + 1:] if b.startswith(loc + " ") else None
        if rest is not None and 1 <= len(rest.split()) <= 3 and not rest.startswith(("state", "oh ", "oh")):
            return True
    # "Bowling Green Falcons" vs displayName; "Miami (OH) RedHawks" vs "Miami (OH)"
    loc = norm(team.get("location", ""))
    return league == "CFB" and b.startswith(loc + " ") and \
        b[len(loc) + 1:] == norm(team.get("name", ""))


def events_near(d: str):
    base = date.fromisoformat(d)
    for league in ("NFL", "CFB"):
        for k in (-1, 0, 1):
            dd = (base + timedelta(days=k)).isoformat()
            for ev in scoreboard(league, dd).get("events", []):
                yield league, ev


def match(g: dict):
    for league, ev in events_near(g["date"]):
        comps = ev["competitions"][0]["competitors"]
        teams = {c["homeAway"]: c for c in comps}
        if "home" not in teams or "away" not in teams:
            continue
        h, a = teams["home"]["team"], teams["away"]["team"]
        if (team_hit(g["home"], h, league) and team_hit(g["away"], a, league)) or \
           (team_hit(g["home"], a, league) and team_hit(g["away"], h, league)):
            return league, ev
    return None, None


CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/{lg}/events/{e}/competitions/{e}/odds"


def _num(x):
    try:
        return float(str(x).replace("+", "")) if x not in (None, "", "EVEN", "even") else (100.0 if x else None)
    except ValueError:
        return None


def core_odds(league: str, event_id: str) -> dict:
    """ESPN core odds: close AND open, any season. Prefer DraftKings, then ESPN BET."""
    d = get(CORE.format(lg=LEAGUE_PATH[league], e=event_id), f"core_{league}_{event_id}")
    items = [i for i in d.get("items", []) if "live" not in ((i.get("provider") or {}).get("name", "").lower())]
    if not items:
        return {}
    rank = {"DraftKings": 0, "ESPN BET": 1}
    i = sorted(items, key=lambda x: rank.get((x.get("provider") or {}).get("name"), 9))[0]
    ho, ao = i.get("homeTeamOdds") or {}, i.get("awayTeamOdds") or {}

    def am(node, *path):
        for k in path:
            node = (node or {}).get(k)
        return _num(node)
    return {"provider": (i.get("provider") or {}).get("name"),
            "home_spread": _num(i.get("spread")) if i.get("spread") is not None else
            am(ho, "close", "pointSpread", "american"),
            "details": i.get("details"),
            "home_spread_odds": _num(ho.get("spreadOdds")) or am(ho, "close", "spread", "american"),
            "away_spread_odds": _num(ao.get("spreadOdds")) or am(ao, "close", "spread", "american"),
            "ml_home": _num(ho.get("moneyLine")), "ml_away": _num(ao.get("moneyLine")),
            "total": _num(i.get("overUnder")),
            "over_odds": _num(i.get("overOdds")), "under_odds": _num(i.get("underOdds")),
            "open_home_spread": am(ho, "open", "pointSpread", "american"),
            "open_total": am(i, "open", "total", "american")}


def close_odds(league: str, event_id: str) -> dict:
    c = core_odds(league, event_id)
    if c.get("home_spread") is not None:
        return c
    s = get(f"{BASE}{LEAGUE_PATH[league]}/summary?event={event_id}", f"sum_{league}_{event_id}")
    for p in s.get("pickcenter", []) or []:
        if p.get("spread") is None and p.get("overUnder") is None:
            continue
        ho, ao = p.get("homeTeamOdds") or {}, p.get("awayTeamOdds") or {}
        return {"provider": (p.get("provider") or {}).get("name"),
                "home_spread": p.get("spread"),       # ESPN: home team's line
                "details": p.get("details"),
                "home_spread_odds": ho.get("spreadOdds"), "away_spread_odds": ao.get("spreadOdds"),
                "ml_home": ho.get("moneyLine"), "ml_away": ao.get("moneyLine"),
                "total": p.get("overUnder"),
                "over_odds": p.get("overOdds"), "under_odds": p.get("underOdds")}
    return {}


def resolve(g: dict) -> dict:
    league, ev = match(g)
    out = dict(g, league=league, event_id=None)
    if not ev:
        return out
    c = ev["competitions"][0]
    teams = {x["homeAway"]: x for x in c["competitors"]}
    out.update(event_id=ev["id"], status=c["status"]["type"]["name"],
               espn_home=teams["home"]["team"]["abbreviation"],
               espn_away=teams["away"]["team"]["abbreviation"],
               espn_home_names=sorted(names(teams["home"]["team"], league)),
               espn_away_names=sorted(names(teams["away"]["team"], league)),
               home_score=int(teams["home"].get("score") or 0),
               away_score=int(teams["away"].get("score") or 0),
               board_home_is_espn_home=team_hit(g["home"], teams["home"]["team"], league))
    out["close"] = close_odds(league, ev["id"]) if out["status"] == "STATUS_FINAL" else {}
    return out


def main(path):
    os.makedirs(CACHE, exist_ok=True)
    games = [g for g in json.load(open(path)) if not g.get("draft")]
    # Warm the scoreboard cache first (each date once), then resolve in parallel.
    days = sorted({(date.fromisoformat(g["date"]) + timedelta(days=k)).isoformat()
                   for g in games for k in (-1, 0, 1)})
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(lambda a: scoreboard(*a), [(lg, d) for d in days for lg in ("NFL", "CFB")]))
    with ThreadPoolExecutor(6) as pool:
        res = list(pool.map(resolve, games))
    miss = [f"{g['season']}-{g['week']}#{g['num']} {g['away']} @ {g['home']}"
            for g in res if not g.get("event_id")]
    print(f"matched {len(res) - len(miss)}/{len(res)}", file=sys.stderr)
    for m in miss[:40]:
        print("  unmatched:", m, file=sys.stderr)
    json.dump(res, sys.stdout, indent=0)


if __name__ == "__main__":
    main(sys.argv[1])
