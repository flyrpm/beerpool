#!/usr/bin/env python3
"""Game context for the live card: ratings, weather, injuries, news. Information only.

  python3 context.py board.json [--games 37,55,63]     # print context for those games

For each game on the card (and the next-best candidates) it pulls ESPN's game summary:
  * FPI   - ESPN's win probability -> implied margin; flags a big disagreement with the market
  * Weather/venue - flags wind/rain for totals (outdoor games only)
  * NFL injury report - flags a starting QB who is Questionable/Doubtful/Out
    (the charter's hard rule: no 5-pointer on an unresolved starter)
  * Headlines - flags injury/suspension/QB words in the game's news
College injury reports are not published by ESPN; headlines are the only signal there.

Nothing here changes a probability or a pick. Every flag is a prompt to look, and each
one must earn its way into the model by backtest after the Week 10 evaluation.
Raw ESPN responses are saved (with fetch time) under the data lake, or data/context/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import teams  # noqa: E402

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/"
PATH = {"NFL": "nfl", "CFB": "college-football"}
MARGIN_SD = {"NFL": 13.5, "CFB": 16.5}
FPI_GAP = 4.0          # points of FPI-vs-market disagreement worth a look
WIND_MPH = 15          # gusts at/above this matter for totals
RAIN_PCT = 50
NEWS_WORDS = re.compile(r"\b(out|injur\w*|suspend\w*|questionable|doubtful|ruled out|"
                        r"starter|starting|qb|quarterback|concussion|transfer|opt(?:s|ed)? out)\b", re.I)
BAD_QB = {"questionable", "doubtful", "out", "injured reserve"}


def raw_dir() -> str:
    lake = os.path.join(ROOT, "data", "lake", "raw", "context")
    return lake if os.path.isdir(os.path.join(ROOT, "data", "lake")) else os.path.join(ROOT, "data", "context")


def fetch_json(url: str, save_as: str | None = None) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode())
    if save_as:
        os.makedirs(os.path.dirname(save_as), exist_ok=True)
        with open(save_as, "w") as f:
            json.dump({"fetched_utc": datetime.now(timezone.utc).isoformat(), "url": url,
                       "data": data}, f)
    return data


# ------------------------------------------------------------------ flags (pure, testable)
def fpi_margin(home_win_pct: float, league: str) -> float:
    """Expected home margin implied by a win probability (normal margin model)."""
    p = min(max(home_win_pct / 100.0, 0.005), 0.995)
    return MARGIN_SD[league] * NormalDist().inv_cdf(p)


def fpi_flag(summary: dict, league: str, side_is_home: bool, side_market_line: float) -> str | None:
    pred = summary.get("predictor") or {}
    try:
        home_pct = float(pred["homeTeam"]["gameProjection"])
    except (KeyError, TypeError, ValueError):
        return None
    m = fpi_margin(home_pct, league)
    side_fpi = m if side_is_home else -m
    side_mkt = -side_market_line              # market's expected margin for our side
    gap = side_fpi - side_mkt
    txt = f"FPI {home_pct:.0f}% home -> our side by {side_fpi:+.1f} vs market {side_mkt:+.1f}"
    if abs(gap) >= FPI_GAP:
        return txt + f"  ** FPI {'likes' if gap > 0 else 'dislikes'} our side by {abs(gap):.1f} **"
    return txt


def weather_flag(summary: dict) -> str | None:
    gi = summary.get("gameInfo") or {}
    venue = gi.get("venue") or {}
    if venue.get("indoor"):
        return "indoor"
    w = gi.get("weather") or {}
    if not w:
        return None
    gust = w.get("gust") or 0
    rain = w.get("precipitation") or 0
    txt = f"{w.get('temperature', '?')}F, gusts {gust} mph, precip {rain}%"
    if gust >= WIND_MPH or rain >= RAIN_PCT:
        return txt + "  ** weather can matter for totals **"
    return txt


def qb_flags(summary: dict) -> list[str]:
    out = []
    for t in summary.get("injuries") or []:
        abbr = (t.get("team") or {}).get("abbreviation", "?")
        for i in t.get("injuries") or []:
            ath = i.get("athlete") or {}
            pos = ((ath.get("position") or {}).get("abbreviation") or "").upper()
            status = (i.get("status") or "").lower()
            if pos == "QB" and status in BAD_QB:
                out.append(f"** {abbr} QB {ath.get('displayName', '?')}: {i.get('status')} **")
    return out


def game_team_words(summary: dict) -> set[str]:
    """Names that identify this game's two teams (location, nickname, abbreviation)."""
    words = set()
    for comp in ((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []:
        t = comp.get("team") or {}
        for k in ("location", "name", "displayName", "shortDisplayName", "abbreviation", "nickname"):
            if t.get(k) and len(t[k]) >= 3:
                words.add(t[k].lower())
    return words


def news_flags(summary: dict, limit: int = 3) -> list[str]:
    """Injury/QB headlines that name one of THIS game's teams (ESPN's NFL news feed is
    league-wide, so unfiltered it would attach other teams' stories)."""
    arts = (summary.get("news") or {}).get("articles") or []
    words = game_team_words(summary)
    hits = []
    for a in arts:
        text = a.get("headline", "") + " " + a.get("description", "")
        if NEWS_WORDS.search(text) and (not words or any(w in text.lower() for w in words)):
            hits.append(a.get("headline", ""))
    return [f"news: {h}" for h in hits[:limit]]


# ------------------------------------------------------------------ ESPN lookups
def find_event(game: dict) -> tuple[str | None, str | None]:
    """(event id, league) for a board game, matched on ESPN team ids."""
    lg = game.get("league", "CFB")
    names = (game.get("names") or "").split(" at ")
    if len(names) != 2:
        return None, lg
    ids = {teams.resolve(n, lg)[0] for n in names}
    if None in ids:
        return None, lg
    day = datetime.fromisoformat(game["kickoff"]).date()
    for d in (day, day + timedelta(days=1), day - timedelta(days=1)):
        q = f"dates={d:%Y%m%d}" + ("&groups=80&limit=300" if lg == "CFB" else "")
        try:
            sb = fetch_json(f"{BASE}{PATH[lg]}/scoreboard?{q}")
        except Exception:
            continue
        for ev in sb.get("events", []):
            got = {c["team"]["id"] for c in ev["competitions"][0]["competitors"]}
            if got == ids:
                return ev["id"], lg
    return None, lg


def game_context(game: dict, cands: list) -> list[str]:
    eid, lg = find_event(game)
    if not eid:
        return ["(no ESPN match for this game)"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = fetch_json(f"{BASE}{PATH[lg]}/summary?event={eid}",
                         os.path.join(raw_dir(), stamp, f"{lg}_{eid}.json"))
    lines = []
    for c in cands:
        if c.side in ("OVER", "UNDER"):
            continue
        f = fpi_flag(summary, lg, c.side == game["home"], c.market_line)
        if f:
            lines.append(f"{c.side}: {f}")
    w = weather_flag(summary)
    if w:
        lines.append(f"weather: {w}")
    lines += qb_flags(summary) + news_flags(summary)
    return lines or ["(nothing notable)"]


def section(board: dict, picks: list) -> str:
    by_num = {g["num"]: g for g in board["games"]}
    out = ["== CONTEXT (information only; flags never change a pick) =="]
    seen = []
    for c in picks:
        if c.game in seen:
            continue
        seen.append(c.game)
        g = by_num.get(c.game)
        if not g:
            continue
        same = [x for x in picks if x.game == c.game]
        out.append(f"  {c.game} {g.get('names', '')}  [{', '.join(x.label for x in same)}]")
        try:
            out += [f"      {line}" for line in game_context(g, same)]
        except Exception as e:
            out.append(f"      (context unavailable: {e})")
    return "\n".join(out)


if __name__ == "__main__":
    import beerpool as bp
    with open(sys.argv[1]) as f:
        board = json.load(f)
    nums = None
    if "--games" in sys.argv:
        nums = {int(x) for x in sys.argv[sys.argv.index("--games") + 1].split(",")}
    cands, _ = bp.build_candidates(board, None, [], bp.Config.production())
    card, _, _ = bp.build_card(cands, cfg=bp.Config.production())
    picks = [c for c in cands if c.game in nums] if nums else card
    print(section(board, picks))
