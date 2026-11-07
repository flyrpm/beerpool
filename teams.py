#!/usr/bin/env python3
"""One team-identity table for the whole project, keyed by ESPN team id.

  python3 teams.py refresh          # rebuild models/teams.json from ESPN's team lists
  python3 teams.py lookup "UNLV Runnin' Rebels" [--league CFB]

Every source names teams its own way: the commissioner's sheet ("San José State", "BOIS",
"No. 7 Alabama", last season's "UNLV Runnin' Rebels"), VegasInsider ("Miami (FL)",
"Hawaii"), ESPN ("Hawai'i", "App State"). build_board.py, fetch_results.py and
run_backtest.py all resolve names through here, so a match means the same ESPN id
everywhere, and an ambiguous name returns None (with a reason) instead of a silent guess.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "models", "teams.json")
SOURCES = {"NFL": ["nfl/teams?limit=100"],
           "CFB": ["college-football/teams?limit=1000",
                   "college-football/teams?groups=81&limit=1000"]}
BASE = "https://site.api.espn.com/apis/site/v2/sports/football/"
TIERS = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{y}/types/2/groups/{g}/teams?limit=400"

# Other sources' spellings -> the ESPN location (or display name) they mean.
ALIASES = {
    "CFB": {
        "miami fl": "miami", "miami florida": "miami", "miami oh": "miami (oh)",
        "miami ohio": "miami (oh)", "hawaii": "hawai'i", "ul monroe": "ul monroe",
        "louisiana monroe": "ul monroe", "ulm": "ul monroe", "louisiana lafayette": "louisiana",
        "ul lafayette": "louisiana", "appalachian state": "app state", "connecticut": "uconn",
        "north carolina state": "nc state", "southern methodist": "smu",
        "central florida": "ucf", "massachusetts": "umass", "fiu": "florida international",
        "sam houston state": "sam houston", "san jose state": "san josé state",
        "southern mississippi": "southern miss", "mississippi": "ole miss",
        "texas am": "texas a&m", "brigham young": "byu", "nevada las vegas": "unlv",
        "texas el paso": "utep", "texas san antonio": "utsa", "alabama birmingham": "uab",
        "louisiana state": "lsu", "texas christian": "tcu", "southern california": "usc",
        "pittsburgh": "pittsburgh", "pitt": "pittsburgh", "middle tennessee state": "middle tennessee",
        "army west point": "army", "air force academy": "air force",
        # the commissioner's sheet abbreviations ESPN spells differently
        "tamu": "texas a&m", "ohst": "ohio state", "bois": "boise state", "af": "air force",
    },
    "NFL": {"washington football team": "washington commanders"},
}


def norm(s: str) -> str:
    s = s.lower().replace("&", "and").replace("é", "e").replace("’", "'").replace("ʻ", "'")
    s = re.sub(r"^\s*(no\.?\s*\d{1,2}\s+|\d{1,2}(?=[a-z]))", "", s)     # rankings
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


# ------------------------------------------------------------------- build / load
def refresh() -> dict:
    out = {}
    for league, paths in SOURCES.items():
        teams = {}
        for path in paths:
            with urllib.request.urlopen(BASE + path, timeout=30) as r:
                data = json.loads(r.read().decode())
            for t in data["sports"][0]["leagues"][0]["teams"]:
                t = t["team"]
                teams[t["id"]] = {k: t.get(k, "") for k in
                                  ("abbreviation", "location", "name", "displayName",
                                   "shortDisplayName", "nickname")}
        out[league] = teams
    # FBS (80) and FCS (81) ids: lower-division namesakes ("Troy Vikings",
    # "Charlotte Saints") must not make "Troy" or "Charlotte" ambiguous.
    from datetime import date
    tier = {}
    for g in (80, 81):
        with urllib.request.urlopen(TIERS.format(y=date.today().year, g=g), timeout=30) as r:
            for item in json.loads(r.read().decode()).get("items", []):
                tier[re.search(r"/teams/(\d+)", item["$ref"]).group(1)] = "FBS" if g == 80 else "FCS"
    for tid, t in out["CFB"].items():
        t["tier"] = tier.get(tid, "lower")
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(out, open(PATH, "w"), indent=0, sort_keys=True)
    return out


_DIR: dict | None = None
_INDEX: dict = {}


def directory() -> dict:
    global _DIR
    if _DIR is None:
        _DIR = json.load(open(PATH)) if os.path.exists(PATH) else refresh()
    return _DIR


def _names(t: dict, league: str) -> set[str]:
    keys = ["location", "displayName", "shortDisplayName", "abbreviation"]
    if league == "NFL":
        keys += ["name", "nickname"]                  # "Bills" alone is unique in the NFL
    return {norm(t[k]) for k in keys if t.get(k)}


def index(league: str) -> dict[str, set[str]]:
    if league not in _INDEX:
        idx: dict[str, set[str]] = {}
        for tid, t in directory()[league].items():
            for n in _names(t, league):
                idx.setdefault(n, set()).add(tid)
        _INDEX[league] = idx
    return _INDEX[league]


def team(tid: str, league: str) -> dict:
    return directory()[league][tid]


# ------------------------------------------------------------------- resolve
def resolve(name: str, league: str) -> tuple[str | None, str]:
    """ESPN id for a team name, or (None, reason). Tries the full name, aliases, then
    shorter word-prefixes ('UNLV Runnin Rebels' -> 'UNLV') so nickname spellings from
    other sources don't matter. Ambiguous -> None."""
    idx = index(league)
    alias = ALIASES.get(league, {})
    words = norm(name).split()
    if not words:
        return None, "empty name"
    for n in range(len(words), 0, -1):
        key, dropped = " ".join(words[:n]), words[n:]
        for k in (key, norm(alias.get(key, key))):
            hits = idx.get(k)
            if not hits:
                continue
            if len(hits) > 1:   # prefer Division I programs over lower-division namesakes
                d1 = {h for h in hits if team(h, league).get("tier", "FBS") != "lower"}
                hits = d1 or hits
            if dropped:         # words were dropped: they must end in the team's nickname
                hits = {h for h in hits
                        if norm(team(h, league).get("name", "")).split()[-1:] == dropped[-1:]}
            if len(hits) == 1:
                return next(iter(hits)), "ok"
            if len(hits) > 1:
                return None, f"'{name}' is ambiguous ({len(hits)} {league} teams)"
    return None, f"'{name}' not found among {league} teams"


def resolve_any(name: str) -> tuple[str | None, str | None]:
    """(league, id) trying NFL first (full names there are unambiguous), then CFB."""
    for league in ("NFL", "CFB"):
        tid, _ = resolve(name, league)
        if tid:
            return league, tid
    return None, None


def _subseq(token: str, text: str) -> bool:
    it = iter(text.upper())
    return all(ch in it for ch in token.upper() if ch.isalnum())


def which_side(token: str, league: str, away_id: str, home_id: str) -> tuple[str | None, str]:
    """Which of two known teams a sheet token ('BOIS', 'M-OH', 'Kansas State Wildcats')
    means. Returns ('away'|'home', reason) or (None, reason) -- never a coin flip."""
    tid, _ = resolve(token, league)
    if tid in (away_id, home_id):
        return ("home" if tid == home_id else "away"), "name"
    t = norm(token).replace(" ", "")
    hits = []
    for side, i in (("away", away_id), ("home", home_id)):
        tm = team(i, league)
        names = {n.replace(" ", "") for n in _names(tm, league)}
        if t in names:
            hits.append(side)
    if len(hits) == 1:
        return hits[0], "abbreviation"
    # Sheet abbreviations ESPN doesn't use (BOIS for BSU, TLSA, OKST...): letters in order.
    subs = [side for side, i in (("away", away_id), ("home", home_id))
            if _subseq(token, team(i, league)["location"] or team(i, league)["displayName"])]
    if len(subs) == 1:
        return subs[0], "letters"
    return None, f"cannot tell which team '{token}' means ({team(away_id, league)['location']} vs {team(home_id, league)['location']})"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        d = refresh()
        print({k: len(v) for k, v in d.items()}, "->", PATH)
    elif len(sys.argv) > 2 and sys.argv[1] == "lookup":
        lg = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None
        for league in ([lg] if lg else ["NFL", "CFB"]):
            tid, why = resolve(sys.argv[2], league)
            print(league, tid, team(tid, league) if tid else why)
    else:
        print(__doc__)
