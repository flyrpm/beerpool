#!/usr/bin/env python3
"""Beer pool weekly pick algorithm (BPN, "Ronnie").

Pipeline (mirrors the charter):
  1. Live board     - drop games that have locked.
  2. Sweep          - every spread and total, sheet vs multi-book consensus.
  3. Price          - calibrate a margin/total distribution to the de-vigged
                      market, then price each side AT THE SHEET NUMBER with
                      push = loss and key-number mass included.
  4. Handicap       - optional manual probability adjustments + tags.
  5. Rank           - by true cover probability, not by stale-line edge.
  6. Construct card - 5-pt slots only for clean picks; one pick per game;
                      no shared thesis; 5-pointers in different environments;
                      no Dallas; never both sides of a game.
  7. Format/verify  - submission block + optional check against the PDF text.

Pure standard library. Usage:
  python3 beerpool.py board.json [--pdf board.pdf] [--now 2026-11-07T09:00]
board.json is normally produced by build_board.py (PDF + live market + notes).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Margin / total distributions with key-number mass
# ---------------------------------------------------------------------------

# Multipliers on a discretized normal, by |margin|. Tuned so that with an
# even game the NFL lands ~14-15% on a 3-point margin and ~8% on 7, the
# usual historical figures. College keys are flatter.
NFL_KEYS = {0: 0.06, 1: 1.05, 2: 0.95, 3: 2.75, 4: 1.25, 5: 0.9, 6: 1.35,
            7: 2.05, 8: 1.0, 9: 0.75, 10: 1.55, 11: 0.8, 12: 0.75, 13: 1.05,
            14: 1.5, 15: 0.8, 16: 1.05, 17: 1.4, 18: 0.9, 20: 1.15, 21: 1.3,
            24: 1.2, 27: 1.15, 28: 1.2}
CFB_KEYS = {0: 0.0, 1: 0.9, 2: 0.9, 3: 1.9, 4: 1.15, 5: 0.9, 6: 1.1,
            7: 1.7, 8: 1.0, 10: 1.35, 11: 0.9, 13: 1.05, 14: 1.4, 17: 1.3,
            21: 1.25, 24: 1.15, 28: 1.2, 31: 1.1, 35: 1.1}
NFL_TOTAL_KEYS = {37: 1.25, 41: 1.35, 43: 1.15, 44: 1.3, 47: 1.25, 51: 1.2,
                  40: 1.1, 48: 1.1, 54: 1.1, 33: 1.1, 30: 1.05}
CFB_TOTAL_KEYS = {41: 1.1, 44: 1.1, 45: 1.1, 48: 1.1, 51: 1.1, 52: 1.1,
                  55: 1.1, 58: 1.05, 59: 1.05, 62: 1.05}

PARAMS = {
    "NFL": {"margin_sd": 13.5, "margin_keys": NFL_KEYS,
            "total_sd": 13.0, "total_keys": NFL_TOTAL_KEYS},
    "CFB": {"margin_sd": 16.5, "margin_keys": CFB_KEYS,
            "total_sd": 16.0, "total_keys": CFB_TOTAL_KEYS},
}


def _norm_pdf(x: float, mu: float, sd: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sd) ** 2)


def margin_pmf(mu: float, league: str) -> dict[int, float]:
    """PMF of home margin (home - away) as integers."""
    p = PARAMS[league]
    keys, sd = p["margin_keys"], p["margin_sd"]
    pmf = {}
    for m in range(-90, 91):
        pmf[m] = _norm_pdf(m, mu, sd) * keys.get(abs(m), 1.0)
    z = sum(pmf.values())
    return {m: v / z for m, v in pmf.items()}


def total_pmf(mu: float, league: str) -> dict[int, float]:
    p = PARAMS[league]
    keys, sd = p["total_keys"], p["total_sd"]
    pmf = {}
    for t in range(0, 141):
        pmf[t] = _norm_pdf(t, mu, sd) * keys.get(t, 1.0)
    z = sum(pmf.values())
    return {t: v / z for t, v in pmf.items()}


def p_strict_above(pmf: dict[int, float], x: float) -> float:
    """P(X > x). Strict: landing on x is a push, and pushes are losses."""
    return sum(v for k, v in pmf.items() if k > x)


def p_strict_below(pmf: dict[int, float], x: float) -> float:
    return sum(v for k, v in pmf.items() if k < x)


def _bisect(f, lo: float, hi: float, target: float, iters: int = 60) -> float:
    """f increasing in its argument; find x with f(x) = target."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Odds helpers
# ---------------------------------------------------------------------------

def american_to_implied(odds: float) -> float:
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def devig(a: float, b: float) -> float:
    """Return the fair probability of side A from two American prices."""
    pa, pb = american_to_implied(a), american_to_implied(b)
    return pa / (pa + pb)


def fmt_line(x: float, signed: bool = True) -> str:
    if signed and x == 0:
        return "PK"
    s = f"{abs(x):g}"
    if not signed:
        return s
    return ("+" if x > 0 else "-") + s


# ---------------------------------------------------------------------------
# Calibration: market -> distribution mean
# ---------------------------------------------------------------------------

def home_spread(fav: str, spread: float, home: str) -> float:
    """Line from the home team's perspective (negative = home favored)."""
    spread = abs(spread)
    return -spread if fav == home else spread


def calibrate_margin(league: str, mkt_home_line: float, p_home_fair: float,
                     p_home_ml: float | None = None) -> float:
    """Mean home margin such that the model reproduces the market price.

    Book prices are conditional on no push (pushes refund), so we match
    P(home covers) / (P(home covers) + P(away covers)).
    """
    def cond_cover(mu: float) -> float:
        pmf = margin_pmf(mu, league)
        win = p_strict_above(pmf, -mkt_home_line)
        lose = p_strict_below(pmf, -mkt_home_line)
        return win / (win + lose)

    mu = _bisect(cond_cover, -70, 70, p_home_fair)
    if p_home_ml is not None:
        def cond_win(m: float) -> float:
            pmf = margin_pmf(m, league)
            w, l = p_strict_above(pmf, 0), p_strict_below(pmf, 0)
            return w / (w + l)
        mu = (mu + _bisect(cond_win, -70, 70, p_home_ml)) / 2
    return mu


def calibrate_total(league: str, mkt_total: float, p_over_fair: float) -> float:
    def cond_over(mu: float) -> float:
        pmf = total_pmf(mu, league)
        o, u = p_strict_above(pmf, mkt_total), p_strict_below(pmf, mkt_total)
        return o / (o + u)
    return _bisect(cond_over, 10, 130, p_over_fair)


# ---------------------------------------------------------------------------
# Board model
# ---------------------------------------------------------------------------

BANNED_TEAMS = {"DAL"}           # Bert will not pick the Cowboys.
NO_FIVE_TAGS = {"qb_uncertain", "model_only", "starter_uncertain",
                "big_move", "steam_against"}
BOOK_SPREAD_TOLERANCE = 1.0      # wider spread among books => no call
BOOK_TOTAL_TOLERANCE = 1.5
BIG_MOVE = 3.0                   # open->now move this big = news we haven't verified
STEAM = 2.0                      # market moved this far AWAY from our side since open


def book_range(books: list[float]) -> float:
    """Range among books, ignoring one stale outlier at each end when there are
    5+ books (Hard Rock / Fanatics often lag the rest of the market)."""
    b = sorted(books)
    if len(b) >= 5:
        b = b[1:-1]
    return b[-1] - b[0]


def movement_tags(now: float, opened: float | None, against_if_up: bool) -> set:
    """Tags from open->now movement for one side.

    Spreads use the side's own line (points received): if it went UP, the market
    is fading that side (dog +12.5 -> +15.5 = money on the favourite).
    Totals: a rising total is money on the OVER, i.e. against the UNDER.
    """
    if opened is None:
        return set()
    move = now - opened
    tags = set()
    if abs(move) >= BIG_MOVE:
        tags.add("big_move")
    if (move if against_if_up else -move) >= STEAM:
        tags.add("steam_against")
    return tags


@dataclass
class Candidate:
    game: int
    league: str
    side: str            # team abbr, or "OVER"/"UNDER"
    label: str           # card text after the game number
    sheet_line: float    # line from this side's perspective (spreads) or total
    market_line: float   # same perspective
    p_market: float      # model cover prob at the sheet number, push = loss
    adj: float = 0.0
    tags: set = field(default_factory=set)
    thesis: str | None = None
    env: str | None = None
    note: str = ""

    @property
    def p(self) -> float:
        return self.p_market + self.adj

    @property
    def number_edge(self) -> float:
        """Points of line value vs the market, from this side's view.
        Spreads: more points for us is better. Totals: under wants higher,
        over wants lower."""
        if self.side == "UNDER":
            return self.sheet_line - self.market_line
        if self.side == "OVER":
            return self.market_line - self.sheet_line
        return self.sheet_line - self.market_line

    @property
    def five_eligible(self) -> bool:
        return not (self.tags & NO_FIVE_TAGS)

    move: str = ""


def parse_time(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def game_lock(game: dict, board: dict) -> datetime | None:
    """Friday games lock at kickoff; everything else at the board default
    (Saturday noon) unless the game overrides it."""
    if game.get("lock"):
        return parse_time(game["lock"])
    ko = parse_time(game.get("kickoff"))
    default = parse_time(board.get("default_lock"))
    if ko and default and ko < default:
        return ko
    return default


def build_candidates(board: dict, now: datetime | None,
                     warnings: list[str]) -> tuple[list[Candidate], list[dict]]:
    cands: list[Candidate] = []
    sweep: list[dict] = []
    for g in board["games"]:
        num, lg = g["num"], g.get("league", "NFL").upper()
        away, home = g["away"], g["home"]
        lock = game_lock(g, board)
        if now and lock and now >= lock:
            sweep.append({"game": num, "matchup": f"{away}@{home}",
                          "status": f"LOCKED ({lock:%a %H:%M})"})
            continue
        mkt = g.get("market") or {}
        notes = g.get("notes", {})

        def mk(side: str, label: str, sheet_l: float, mkt_l: float,
               p: float, key: str, auto_tags: set = frozenset(), move: str = "") -> Candidate:
            n = notes.get(key, {})
            tags = (set(auto_tags) | set(n.get("tags", []))) - set(n.get("clear_tags", []))
            c = Candidate(num, lg, side, label, sheet_l, mkt_l, p,
                          adj=n.get("adj", 0.0), tags=tags,
                          thesis=n.get("thesis"), env=n.get("env") or g.get("env"),
                          note=n.get("note", ""))
            c.move = move
            return c

        row = {"game": num, "matchup": f"{away}@{home}", "status": "open"}

        # ---- spread ----
        if g.get("sheet_fav") is not None and mkt.get("fav"):
            sheet_h = home_spread(g["sheet_fav"], g["sheet_spread"], home)
            mkt_h = home_spread(mkt["fav"], mkt["spread"], home)
            books = mkt.get("books", {}).get("spread")
            conflict = books and book_range(books) > BOOK_SPREAD_TOLERANCE
            if mkt["fav"] == home:
                p_home = devig(mkt.get("fav_price", -110), mkt.get("dog_price", -110))
            else:
                p_home = devig(mkt.get("dog_price", -110), mkt.get("fav_price", -110))
            p_home_ml = None
            if mkt.get("ml_home") is not None and mkt.get("ml_away") is not None:
                p_home_ml = devig(mkt["ml_home"], mkt["ml_away"])
            mu = calibrate_margin(lg, mkt_h, p_home, p_home_ml)
            pmf = margin_pmf(mu, lg)
            p_home_sheet = p_strict_above(pmf, -sheet_h)   # home covers sheet
            p_away_sheet = p_strict_below(pmf, -sheet_h)
            row.update(sheet=f"{g['sheet_fav']} -{fmt_line(g['sheet_spread'], False)}",
                       market=f"{mkt['fav']} -{fmt_line(mkt['spread'], False)}",
                       spread_edge=round(mkt_h - sheet_h, 2),  # + favors home
                       p_home=round(p_home_sheet, 4), p_away=round(p_away_sheet, 4),
                       fair_margin=round(mu, 2))
            open_h = mkt.get("open_home")
            mv = f"open {fmt_line(open_h)}" if open_h is not None else ""
            if conflict:
                row["spread_flag"] = f"NO CALL: books disagree {books}"
            else:
                cands.append(mk(home, f"{home} {fmt_line(sheet_h)}", sheet_h, mkt_h,
                                p_home_sheet, home,
                                movement_tags(mkt_h, open_h, True), mv))
                cands.append(mk(away, f"{away} {fmt_line(-sheet_h)}", -sheet_h, -mkt_h,
                                p_away_sheet, away,
                                movement_tags(-mkt_h, None if open_h is None else -open_h, True),
                                mv.replace(fmt_line(open_h), fmt_line(-open_h)) if mv else ""))

        # ---- total ----
        if g.get("sheet_total") is not None and mkt.get("total") is not None:
            st, mt = g["sheet_total"], mkt["total"]
            books = mkt.get("books", {}).get("total")
            conflict = books and book_range(books) > BOOK_TOTAL_TOLERANCE
            p_over = devig(mkt.get("over_price", -110), mkt.get("under_price", -110))
            mu_t = calibrate_total(lg, mt, p_over)
            tpmf = total_pmf(mu_t, lg)
            po, pu = p_strict_above(tpmf, st), p_strict_below(tpmf, st)
            row.update(sheet_total=st, market_total=mt, total_edge=round(st - mt, 2),
                       p_over=round(po, 4), p_under=round(pu, 4))
            open_t = mkt.get("open_total")
            mv = f"open {fmt_line(open_t, False)}" if open_t is not None else ""
            if conflict:
                row["total_flag"] = f"NO CALL: books disagree {books}"
            else:
                pair = f"{away}/{home}"
                cands.append(mk("OVER", f"{pair} OVER {fmt_line(st, False)}", st, mt, po, "OVER",
                                movement_tags(mt, open_t, False), mv))
                cands.append(mk("UNDER", f"{pair} UNDER {fmt_line(st, False)}", st, mt, pu, "UNDER",
                                movement_tags(mt, open_t, True), mv))
        sweep.append(row)

    # Hard constraint: never pick Dallas.
    kept = [c for c in cands if c.side not in BANNED_TEAMS]
    return kept, sweep


# ---------------------------------------------------------------------------
# Card construction
# ---------------------------------------------------------------------------

def build_card(cands: list[Candidate], thin_threshold: float = 0.53):
    """Greedy is optimal here: points per slot are fixed, so the highest
    probabilities go to the highest-value slots, subject to constraints."""
    ranked = sorted(cands, key=lambda c: c.p, reverse=True)
    card: list[Candidate] = []
    used_games, used_theses, used_envs = set(), set(), set()

    def ok(c: Candidate, five: bool) -> bool:
        if c.game in used_games:
            return False                      # one pick per game (never both sides)
        if c.thesis and c.thesis in used_theses:
            return False                      # don't stack one thesis
        if five:
            if not c.five_eligible:
                return False                  # unresolved starter / model-only
            env = c.env or f"game{c.game}"
            if env in used_envs:
                return False                  # 5-pointers in different environments
        return True

    def take(c: Candidate, five: bool):
        card.append(c)
        used_games.add(c.game)
        if c.thesis:
            used_theses.add(c.thesis)
        if five:
            used_envs.add(c.env or f"game{c.game}")

    for _ in range(2):
        for c in ranked:
            if ok(c, True):
                take(c, True)
                break
    for _ in range(3):
        for c in ranked:
            if c not in card and ok(c, False):
                take(c, False)
                break

    thin = not ranked or ranked[0].p < thin_threshold
    return card, thin, ranked


def mega_gain(p: float) -> float:
    """MEGA vs a normal 5-pointer: +10/-5 vs +5/0 => 10p - 5."""
    return 10 * p - 5


def submission_block(week: str, card: list[Candidate], mega_game: int | None = None) -> str:
    lines = [f"Ronnie - {week}"]
    for i, c in enumerate(card, 1):
        s = f"{i}. {c.game} {c.label}"
        if mega_game is not None and c.game == mega_game:
            s += " Mega-Pick"
        lines.append(s)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF verification
# ---------------------------------------------------------------------------

def verify_against_pdf(card: list[Candidate], pdf_path: str) -> list[str]:
    text = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                          capture_output=True, text=True, check=True).stdout
    out = []
    for c in card:
        num = fmt_line(abs(c.sheet_line), False)
        hit = None
        for line in text.splitlines():
            if re.search(rf"(?<!\d){c.game}(?!\d)", line) and \
               re.search(rf"(?<![\d.]){re.escape(num)}(?![\d])", line):
                hit = line.strip()
                break
        status = "OK " if hit else "?? "
        out.append(f"{status} {c.game} {c.label:<26} <- sheet: {hit or 'NOT FOUND - check by hand'}")
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(board: dict, now: datetime | None, pdf: str | None) -> str:
    warnings: list[str] = []
    cands, sweep = build_candidates(board, now, warnings)
    card, thin, ranked = build_card(cands)
    out = []

    out.append("== SWEEP (sheet vs consensus; probabilities at SHEET number, push = loss) ==")
    for r in sweep:
        if r["status"] != "open":
            out.append(f"{r['game']:>4} {r['matchup']:<12} {r['status']}")
            continue
        parts = [f"{r['game']:>4} {r['matchup']:<12}"]
        if "sheet" in r:
            parts.append(f"sprd {r['sheet']:<10} mkt {r['market']:<10} "
                         f"home {r['p_home']:.3f} away {r['p_away']:.3f}")
            if r.get("spread_flag"):
                parts.append(r["spread_flag"])
        if "sheet_total" in r:
            parts.append(f"| tot {r['sheet_total']:g} mkt {r['market_total']:g} "
                         f"O {r['p_over']:.3f} U {r['p_under']:.3f}")
            if r.get("total_flag"):
                parts.append(r["total_flag"])
        out.append("  ".join(parts))

    out.append("\n== TOP CANDIDATES (ranked by cover probability) ==")
    for c in ranked[:15]:
        flags = []
        if c.adj:
            flags.append(f"adj {c.adj:+.3f}")
        if not c.five_eligible:
            flags.append("3-pt max (" + ",".join(sorted(c.tags & NO_FIVE_TAGS)) + ")")
        if c.number_edge > 0:
            flags.append(f"+{c.number_edge:g} pts vs mkt {fmt_line(c.market_line, c.side not in ('OVER', 'UNDER'))}")
        if c.move:
            flags.append(c.move)
        out.append(f"  {c.p:.3f}  {c.game:>4} {c.label:<26} {' | '.join(flags)}")

    out.append("\n== CARD ==")
    if thin:
        out.append("THIN BOARD: nothing grades 53%+. Best available below, labeled honestly.")
    exp = 0.0
    for i, c in enumerate(card, 1):
        pts = 5 if i <= 2 else 3
        exp += pts * c.p
        out.append(f"  Pick {i} ({pts}) {c.game} {c.label:<26} p={c.p:.3f}"
                   + (f"  [{c.note}]" if c.note else ""))
    out.append(f"  Expected points: {exp:.2f} / 19")
    if len(card) < 5:
        out.append(f"  WARNING: only {len(card)} legal picks found.")

    mega = None
    req = board.get("mega")  # {"game": 62} to fire; info edge is a human call
    if card:
        top = card[0]
        out.append(f"  MEGA on Pick 1 would add {mega_gain(top.p):+.2f} pts EV "
                   f"(fire only on a genuine information edge).")
        if req and req.get("game") in {c.game for c in card[:2]}:
            mega = req["game"]

    out.append("\n== SUBMISSION ==")
    out.append("```")
    out.append(submission_block(board.get("week", "Week ?"), card, mega))
    out.append("```")

    if pdf:
        out.append("\n== PDF CHECK (sheet line -> our side) ==")
        out.extend(verify_against_pdf(card, pdf))
    out.extend(warnings)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--pdf")
    ap.add_argument("--now", help="ISO time for lock checks (default: board 'now' or real time)")
    a = ap.parse_args(argv)
    with open(a.board) as f:
        board = json.load(f)
    # Board times are Eastern; compare against Eastern wall-clock time.
    now = parse_time(a.now or board.get("now")) or \
        datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    print(report(board, now, a.pdf))


if __name__ == "__main__":
    main()
