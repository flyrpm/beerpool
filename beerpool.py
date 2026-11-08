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
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, fields, replace
from functools import lru_cache
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


# Fast path: cumulative tables cached on the mean rounded to 0.01 pt. Pricing a board
# calls these thousands of times; the dict versions above stay for tools and tests.
class _Cum:
    __slots__ = ("lo", "cum")

    def __init__(self, pmf: dict[int, float]):
        self.lo = min(pmf)
        acc, out = 0.0, []
        for k in range(self.lo, max(pmf) + 1):
            acc += pmf.get(k, 0.0)
            out.append(acc)
        self.cum = out

    def le(self, k: int) -> float:          # P(X <= k)
        i = k - self.lo
        if i < 0:
            return 0.0
        return self.cum[min(i, len(self.cum) - 1)]

    def above(self, x: float) -> float:     # P(X > x), push = loss
        return 1.0 - self.le(math.floor(x))

    def below(self, x: float) -> float:     # P(X < x)
        return self.le(math.ceil(x) - 1)


@lru_cache(maxsize=8192)
def _margin_cum(mu_q: float, league: str) -> _Cum:
    return _Cum(margin_pmf(mu_q, league))


@lru_cache(maxsize=8192)
def _total_cum(mu_q: float, league: str) -> _Cum:
    return _Cum(total_pmf(mu_q, league))


def margin_cum(mu: float, league: str) -> _Cum:
    return _margin_cum(round(mu, 2), league)


def total_cum(mu: float, league: str) -> _Cum:
    return _total_cum(round(mu, 2), league)


def _bisect(f, lo: float, hi: float, target: float, tol: float = 0.005) -> float:
    """f increasing in its argument; find x with f(x) = target (to tol points)."""
    while hi - lo > tol:
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
        c = margin_cum(mu, league)
        win, lose = c.above(-mkt_home_line), c.below(-mkt_home_line)
        return win / (win + lose)

    mu = _bisect(cond_cover, -70, 70, p_home_fair)
    if p_home_ml is not None:
        def cond_win(m: float) -> float:
            c = margin_cum(m, league)
            w, l = c.above(0), c.below(0)
            return w / (w + l)
        mu = (mu + _bisect(cond_win, -70, 70, p_home_ml)) / 2
    return mu


def calibrate_total(league: str, mkt_total: float, p_over_fair: float) -> float:
    def cond_over(mu: float) -> float:
        c = total_cum(mu, league)
        o, u = c.above(mkt_total), c.below(mkt_total)
        return o / (o + u)
    return _bisect(cond_over, 10, 130, p_over_fair)


# ---------------------------------------------------------------------------
# Board model
# ---------------------------------------------------------------------------

BANNED_TEAMS = {"DAL"}           # Bert will not pick the Cowboys.
NO_FIVE_TAGS = {"qb_uncertain", "model_only", "starter_uncertain",
                "big_move", "steam_against", "huge_edge"}
CALIBRATION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "calibration.json")
EDGE_BUCKETS = (("<=0", -99, 0.0), ("0.5", 0.5, 0.5), ("1-1.5", 1.0, 1.5),
                ("2-3", 2.0, 3.0), ("3.5+", 3.5, 99))


@dataclass(frozen=True)
class Config:
    """Every tunable in one place. Pass it to build_candidates / build_card / report.
    Nothing in the engine reads module-level settings, so a backtest variant can never
    leak into the next one or into the live card."""
    # Totals/spreads shrink toward 50% (used only when no calibration table is loaded).
    total_shrink: float = 0.5
    spread_shrink: float = 1.0
    # big_move (3+ pt open->now move toward us) caps at 3 pts? Backtest: no.
    big_move_caps: bool = False
    # Huge-edge cap: edges >= huge_edge priced at huge_edge_p and 3-pt max. None = off.
    huge_edge: float = 3.5
    huge_edge_p: float | None = None
    # Calibration table (type x edge bucket -> cover rate). Replaces the shrinks when set.
    calibration: dict | None = None
    # 5-pt slot rule: spreads with a five_min_edge..five_max_edge pt edge. None = off.
    five_min_edge: float | None = 1.5
    five_max_edge: float = 3.0
    five_spreads_only: bool = True
    # Weekly-notes probability nudges are clamped to +/- this.
    note_adj_cap: float = 0.02
    # Charter (Bert's Three Locks, after Week 9). Off by default so frozen configs
    # (ronnie-v1) rebuild exactly; production() turns it on.
    #   5-pt slots never hold: a spread dog of +five_max_dog or more, a pick under
    #   five_min_p, or an unverified big line move. No pick under card_min_p at all.
    #   Slots are ordered by probability, and every card is gated before it is shown
    #   as sendable (see gate_card).
    charter: bool = False
    five_max_dog: float = 10.0
    five_min_p: float = 0.54
    card_min_p: float = 0.52

    @staticmethod
    def production() -> "Config":
        cal = None
        if os.path.exists(CALIBRATION_PATH):
            with open(CALIBRATION_PATH) as f:
                cal = json.load(f)
        return Config(calibration=cal, charter=True)

    @staticmethod
    def legacy() -> "Config":
        """The engine as first merged: no calibration/5-pt rule, big moves cap, no shrink."""
        return Config(total_shrink=1.0, big_move_caps=True, five_min_edge=None)

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)

    def describe(self) -> str:
        bits = ["calibrated" if self.calibration else f"shrink totals {self.total_shrink}"]
        if self.five_min_edge is not None:
            bits.append(f"5-pt = spreads w/ {self.five_min_edge:g}-{self.five_max_edge:g} pt edge")
        if self.huge_edge_p is not None:
            bits.append(f"huge-edge cap {self.huge_edge_p}")
        bits.append("big moves cap" if self.big_move_caps else "big moves warn")
        if self.charter:
            bits.append(f"charter (no +{self.five_max_dog:g} dog / <{self.five_min_p:.0%} / "
                        f"unverified move in 5 slots; card >= {self.card_min_p:.0%})")
        return ", ".join(bits)


def edge_bucket(edge: float) -> str:
    for name, lo, hi in EDGE_BUCKETS:
        if lo <= edge <= hi:
            return name
    return "<=0"


def calibrate(p_raw: float, kind: str, edge: float, table: dict | None) -> float:
    """p = bucket cover rate + 0.5 * (raw p - bucket's mean raw p): the bucket sets the
    level, the model still orders picks within the bucket."""
    if not table:
        return p_raw
    cell = table.get(kind, {}).get(edge_bucket(edge))
    if not cell:
        return p_raw
    return min(0.75, max(0.25, cell["rate"] + 0.5 * (p_raw - cell["mean_p"])))
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

    move: str = ""
    big_move_caps: bool = False   # copied from the Config that built this candidate

    @property
    def five_eligible(self) -> bool:
        blocking = NO_FIVE_TAGS if self.big_move_caps else NO_FIVE_TAGS - {"big_move"}
        return not (self.tags & blocking)


def five_bans(c: "Candidate", cfg: "Config") -> list[str]:
    """Why this candidate may not hold a 5-point slot under cfg (empty = allowed)."""
    why = []
    if not Candidate.five_eligible.fget(c):
        why.append("flag: " + ",".join(sorted(c.tags & NO_FIVE_TAGS)))
    if cfg.charter:
        if c.side not in ("OVER", "UNDER") and c.sheet_line >= cfg.five_max_dog:
            why.append(f"dog +{c.sheet_line:g} (>= +{cfg.five_max_dog:g})")
        if c.p < cfg.five_min_p:
            why.append(f"p={c.p:.3f} < {cfg.five_min_p}")
        if "big_move" in c.tags and not c.big_move_caps:
            why.append("unverified big line move")
    return why


def shrink(p: float, k: float) -> float:
    return 0.5 + k * (p - 0.5)


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


def build_candidates(board: dict, now: datetime | None, warnings: list[str],
                     cfg: Config | None = None) -> tuple[list[Candidate], list[dict]]:
    cfg = cfg or Config.production()
    cal = cfg.calibration
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
            adj = max(-cfg.note_adj_cap, min(cfg.note_adj_cap, n.get("adj", 0.0)))
            if adj != n.get("adj", 0.0):
                warnings.append(f"note adj for {num} {key} clamped to {adj:+.3f}")
            c = Candidate(num, lg, side, label, sheet_l, mkt_l, p,
                          adj=adj, tags=tags, big_move_caps=cfg.big_move_caps,
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
            conflict = bool(books) and book_range(books) > BOOK_SPREAD_TOLERANCE
            if mkt["fav"] == home:
                p_home = devig(mkt.get("fav_price", -110), mkt.get("dog_price", -110))
            else:
                p_home = devig(mkt.get("dog_price", -110), mkt.get("fav_price", -110))
            p_home_ml = None
            if mkt.get("ml_home") is not None and mkt.get("ml_away") is not None:
                p_home_ml = devig(mkt["ml_home"], mkt["ml_away"])
            mu = calibrate_margin(lg, mkt_h, p_home, p_home_ml)
            cum = margin_cum(mu, lg)
            k = 1.0 if cal else cfg.spread_shrink
            p_home_sheet = shrink(cum.above(-sheet_h), k)  # home covers sheet
            p_away_sheet = shrink(cum.below(-sheet_h), k)
            if cal:
                p_home_sheet = calibrate(p_home_sheet, "spread", sheet_h - mkt_h, cal)
                p_away_sheet = calibrate(p_away_sheet, "spread", mkt_h - sheet_h, cal)
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
            conflict = bool(books) and book_range(books) > BOOK_TOTAL_TOLERANCE
            p_over = devig(mkt.get("over_price", -110), mkt.get("under_price", -110))
            mu_t = calibrate_total(lg, mt, p_over)
            tcum = total_cum(mu_t, lg)
            k = 1.0 if cal else cfg.total_shrink
            po = shrink(tcum.above(st), k)
            pu = shrink(tcum.below(st), k)
            if cal:
                po, pu = calibrate(po, "total", mt - st, cal), calibrate(pu, "total", st - mt, cal)
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
    if cfg.huge_edge_p is not None:
        for c in kept:
            if c.number_edge >= cfg.huge_edge:
                c.adj = min(c.adj, cfg.huge_edge_p - c.p_market)
                c.tags.add("huge_edge")
    return kept, sweep


# ---------------------------------------------------------------------------
# Card construction
# ---------------------------------------------------------------------------

def build_card(cands: list[Candidate], thin_threshold: float = 0.53, cfg: Config | None = None):
    """Exact search: fill legal slots, preserve sweet-spot priority, then maximize EV.

    The first two entries always satisfy five-point eligibility. If no legal pair
    exists return no card; otherwise return the largest feasible card (up to five).
    Stable input order breaks equal-EV ties, preserving optimal historical cards.
    """
    cfg = cfg or Config.production()
    ranked = sorted(cands, key=lambda c: c.p, reverse=True)
    thin = not ranked or ranked[0].p < thin_threshold
    if cfg.charter:
        return _charter_card(cands, thin_threshold, cfg)
    pool = ranked

    def sweet(c):
        return (cfg.five_min_edge is not None
                and (not cfg.five_spreads_only or c.side not in ("OVER", "UNDER"))
                and cfg.five_min_edge <= c.number_edge <= cfg.five_max_edge)

    def compatible(c, chosen):
        return all(c.game != x.game and not (c.thesis and c.thesis == x.thesis)
                   for x in chosen)

    # First seek a full card. Only an infeasible full board permits fewer slots.
    fives = [c for c in pool if c.five_eligible]
    for size in range(5, 1, -1):
        best, best_ev = None, float("-inf")
        best_sweet = -1
        for i, a in enumerate(fives):
            for b in fives[i + 1:]:
                if not compatible(b, [a]):
                    continue
                if (a.env or f"game{a.game}") == (b.env or f"game{b.game}"):
                    continue
                ns = int(sweet(a)) + int(sweet(b))
                if ns < best_sweet:
                    continue
                rest = [c for c in pool if compatible(c, [a, b])]
                need = size - 2
                base = 5 * (a.p + b.p)

                def search(start, picked, value):
                    nonlocal best, best_ev, best_sweet
                    left = need - len(picked)
                    if len(rest) - start < left:
                        return
                    # Optimistic bound ignores conflicts among remaining candidates.
                    upper = value + 3 * sum(c.p for c in rest[start:start + left])
                    if ns == best_sweet and upper <= best_ev + 1e-12:
                        return
                    if left == 0:
                        best, best_ev, best_sweet = [a, b] + picked, value, ns
                        return
                    for j in range(start, len(rest) - left + 1):
                        c = rest[j]
                        if compatible(c, picked):
                            search(j + 1, picked + [c], value + 3 * c.p)

                search(0, [], base)
        if best is not None:
            return best, thin, ranked
    return [], thin, ranked


@dataclass
class _Chartered(Candidate):
    """A candidate whose 5-pt eligibility is the charter's (used inside build_card)."""
    cfg: "Config | None" = None
    orig: "Candidate | None" = None

    @property
    def five_eligible(self) -> bool:  # type: ignore[override]
        return not five_bans(self, self.cfg)


def _charter_card(cands: list[Candidate], thin_threshold: float, cfg: "Config"):
    """The same exact optimizer, with the charter deciding 5-pt eligibility.

    1. Picks >= card_min_p only. 2. If that can't fill five, all picks (thin board).
    3. If no legal 5-pt pair exists at all, the best available five, labelled thin.
    Never returns an empty card when five distinct games exist: a blank card scores 0.
    Slots come out in probability order (5s, then 3s)."""
    base = cfg.with_(charter=False)
    ranked = sorted(cands, key=lambda c: c.p, reverse=True)
    thin = not ranked or ranked[0].p < thin_threshold

    def wrap(cs):
        return [_Chartered(**{f.name: getattr(c, f.name) for f in fields(Candidate)},
                           cfg=cfg, orig=c) for c in cs]

    def order(card):
        o = [w.orig for w in card]
        return (sorted(o[:2], key=lambda c: c.p, reverse=True)
                + sorted(o[2:], key=lambda c: c.p, reverse=True))

    for pool, is_thin in (([c for c in cands if c.p >= cfg.card_min_p], thin), (cands, True)):
        card, _, _ = build_card(wrap(pool), thin_threshold, base)
        if len(card) == 5:
            return order(card), is_thin, ranked
    # No legal 5-pt pair anywhere: best available five, distinct games, labelled thin.
    card, games = [], set()
    for c in ranked:
        if c.game not in games and not (c.thesis and any(c.thesis == x.thesis for x in card)):
            card.append(c)
            games.add(c.game)
        if len(card) == 5:
            break
    return card, True, ranked


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
# Card gate: every card (engine, another model, a hand swap) passes here before it
# is shown as sendable.
# ---------------------------------------------------------------------------

CARD_LINE = re.compile(r"^\s*(\d+)\.\s*(\d+)\s+(.+?)\s*$")
LINE_TAIL = re.compile(r"^(?P<team>.*?)\s*(?P<line>[-+]?\d+(?:\.\d+)?)$")


def parse_card(text: str) -> list[tuple[int, int, str]]:
    """'1. 37 MRSH +10.5' -> (slot, game, rest). Headers and 'Mega-Pick' are ignored."""
    out = []
    for line in text.splitlines():
        m = CARD_LINE.match(line.replace("`", ""))
        if m:
            rest = re.sub(r"\s*mega-?pick\s*$", "", m.group(3), flags=re.I)
            out.append((int(m.group(1)), int(m.group(2)), rest))
    return out


def _cnorm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9/+\-. ]", " ", s.upper())).strip()


def _side_names(board: dict | None, game: int) -> dict[str, list[str]]:
    g = next((g for g in (board or {}).get("games", []) if g.get("num") == game), None)
    if not g:
        return {}
    out = {g["away"]: [g["away"]], g["home"]: [g["home"]]}
    parts = re.split(r"\s+at\s+", g.get("names") or "", maxsplit=1)
    if len(parts) == 2:
        out[g["away"]].append(_cnorm(parts[0]))
        out[g["home"]].append(_cnorm(parts[1]))
    return out


def side_matches(token: str, side: str, game: int, board: dict | None) -> bool:
    """The card's team text must be the side's abbreviation or its sheet name. A single
    word counts only if it is not in the opponent's name too (MICHIGAN != Michigan State)."""
    tok = _cnorm(token)
    if tok == side.upper():
        return True
    names = _side_names(board, game)
    if side not in names:
        return False
    if tok in names[side][1:]:
        return True
    hit = any(re.search(rf"\b{re.escape(tok)}\b", n) for n in names[side][1:])
    clash = any(re.search(rf"\b{re.escape(tok)}\b", n)
                for s2, ns in names.items() if s2 != side for n in ns[1:])
    return hit and not clash and len(tok) >= 4


def match_pick(cands: list["Candidate"], game: int, rest: str,
               board: dict | None = None) -> "Candidate | None":
    """Requires an explicit line equal to the sheet line from that side's view, plus a
    verified team identity (spreads) or OVER/UNDER (totals)."""
    m = LINE_TAIL.match(_cnorm(rest))
    if not m:
        return None
    team, line = m.group("team").strip(), float(m.group("line"))
    words = team.split()
    signed = re.search(r"[-+]\d", rest) is not None
    for c in cands:
        if c.game != game:
            continue
        if c.side in ("OVER", "UNDER"):
            if c.side in words and abs(c.sheet_line - abs(line)) < 1e-9:
                return c
        elif ("OVER" not in words and "UNDER" not in words and signed
              and abs(c.sheet_line - line) < 1e-9 and side_matches(team, c.side, game, board)):
            return c
    return None


@dataclass
class Gate:
    passed: bool
    problems: list[str]
    picks: list[tuple[int, "Candidate"]]
    warnings: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        head = "GATE: FAIL" if not self.passed else ("GATE: PASS (THIN BOARD)" if self.warnings else "GATE: PASS")
        out = [head]
        out += [f"  x {p}" for p in self.problems]
        out += [f"  ! {w}" for w in self.warnings]
        exp = 0.0
        for slot, c in self.picks:
            pts = 5 if slot <= 2 else 3
            exp += pts * c.p
            out.append(f"  Pick {slot} ({pts}) {c.game} {c.label:<22} p={c.p:.3f}"
                       f"  flags: {','.join(sorted(c.tags)) or '-'}")
        out.append(f"  Expected points: {exp:.2f}")
        return out


def gate_card(card_text: str, cands: list["Candidate"], board: dict | None,
              cfg: "Config") -> Gate:
    """The pool rules (and, with cfg.charter, the Three Locks) applied to any card."""
    probs: list[str] = []
    warns: list[str] = []
    # A rule can only be enforced if the board offers a legal alternative. On a thin
    # board the shortfall is a warning (you must still send five picks), never silence.
    games_ok = {c.game for c in cands if c.p >= cfg.card_min_p}
    fives_ok = {c.game for c in cands if c.p >= cfg.card_min_p and not five_bans(c, cfg)}
    entries = parse_card(card_text)
    slots = [e[0] for e in entries]
    if slots != [1, 2, 3, 4, 5]:
        probs.append(f"slots must be 1-5 exactly once and in order (got {slots or 'none'})")
    picks, games = [], set()
    for slot, game, rest in entries:
        c = match_pick(cands, game, rest, board)
        if c is None:
            probs.append(f"Pick {slot}: '{game} {rest}' is not a side on the board at that "
                         "line (typo, wrong team or line, or game locked)")
            continue
        if game in games:
            probs.append(f"Pick {slot}: game {game} used twice")
        games.add(game)
        if c.side == "DAL":
            probs.append(f"Pick {slot}: Dallas pick (house rule)")
        if cfg.charter and c.p < cfg.card_min_p:
            msg = f"Pick {slot}: {game} {c.label} p={c.p:.3f} < {cfg.card_min_p}"
            (warns if len(games_ok) < 5 else probs).append(
                msg + (" (thin board: fewer than 5 games clear it)" if len(games_ok) < 5 else ""))
        if slot <= 2:
            bans = five_bans(c, cfg)
            if bans:
                msg = (f"Pick {slot} (5 pts): {game} {c.label} can't be a 5-pointer: "
                       + "; ".join(bans))
                if cfg.charter and len(fives_ok) < 2:
                    warns.append(msg + " (thin board: no legal pair of 5-pointers exists)")
                else:
                    probs.append(msg)
        picks.append((slot, c))
    for i, (sa, a) in enumerate(picks):
        for sb, b in picks[i + 1:]:
            if a.thesis and a.thesis == b.thesis:
                probs.append(f"Picks {sa} and {sb} share a thesis ({a.thesis})")
    five = [c for s, c in picks if s <= 2]
    if len(five) == 2 and (five[0].env or f"game{five[0].game}") == (five[1].env or f"game{five[1].game}"):
        probs.append(f"both 5-pointers are in the same environment ({five[0].env})")
    if cfg.charter and picks:
        eligible = [c for c in cands if c.p >= cfg.card_min_p and not five_bans(c, cfg)]
        p1 = next((c for s, c in picks if s == 1), None)
        if eligible and p1 is not None:
            best = max(eligible, key=lambda c: c.p)
            if p1.p + 0.005 < best.p:
                probs.append(f"Pick 1 is {p1.game} {p1.label} (p={p1.p:.3f}); the best "
                             f"5-eligible pick is {best.game} {best.label} (p={best.p:.3f})")
        threes = [c for s, c in picks if s > 2 and not five_bans(c, cfg)]
        if five and threes and max(c.p for c in threes) > min(c.p for c in five) + 0.005:
            t = max(threes, key=lambda c: c.p)
            probs.append(f"{t.game} {t.label} (p={t.p:.3f}) sits in a 3 slot but outranks a 5-pointer")
    return Gate(not probs, probs, picks, warns)


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

def report(board: dict, now: datetime | None, pdf: str | None, cfg: Config | None = None,
           gate_out: list | None = None) -> str:
    """The weekly report. If gate_out is a list, the Gate is appended to it."""
    cfg = cfg or Config.production()
    warnings: list[str] = list(board.get("warnings", []))
    cands, sweep = build_candidates(board, now, warnings, cfg)
    card, thin, ranked = build_card(cands, cfg=cfg)
    out = [f"{board.get('week', 'Week ?')} | market as of {board.get('as_of', 'unknown')}"
           f" | run at {now:%Y-%m-%d %H:%M} ET" if now else "",
           f"engine: {cfg.describe()}", ""]

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

    block = submission_block(board.get("week", "Week ?"), card, mega)
    gate = gate_card(block, cands, board, cfg) if card else Gate(False, ["no complete legal card"], [])
    out.append("\n== GATE ==")
    out.extend(gate.lines())
    if gate.passed:
        out.append("\n== SUBMISSION (gate passed) ==")
        out.append("```")
        out.append(block)
        out.append("```")
    else:
        out.append("\n== SUBMISSION: NONE -- DO NOT SEND ==")
        out.append("  No card passes the rules. Thin board: build by hand and run --check.")

    if pdf and gate.passed:
        out.append("\n== PDF CHECK (sheet line -> our side) ==")
        out.extend(verify_against_pdf(card, pdf))
    if warnings:
        out.append("\n== WARNINGS ==")
        out.extend("  " + w for w in warnings)
    if gate_out is not None:
        gate_out.append(gate)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--pdf")
    ap.add_argument("--now", help="ISO time for lock checks (default: board 'now' or real time)")
    ap.add_argument("--legacy", action="store_true", help="run the engine as first merged")
    ap.add_argument("--check", metavar="CARD_TXT",
                    help="gate any card (file, or '-' for stdin): prints GATE: PASS/FAIL, exit 1 on fail")
    ap.add_argument("--save-run", metavar="DIR",
                    help="archive board.json + card.txt under DIR/<timestamp>/ (reproducible)")
    a = ap.parse_args(argv)
    with open(a.board) as f:
        board = json.load(f)
    # Board times are Eastern; compare against Eastern wall-clock time.
    now = parse_time(a.now or board.get("now")) or \
        datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    cfg = Config.legacy() if a.legacy else Config.production()
    if a.check:
        cands, _ = build_candidates(board, now, [], cfg)
        txt = sys.stdin.read() if a.check == "-" else open(a.check).read()
        g = gate_card(txt, cands, board, cfg)
        print("\n".join(g.lines()))
        sys.exit(0 if g.passed else 1)
    gates: list = []
    text = report(board, now, a.pdf, cfg, gates)
    print(text)
    if a.save_run:
        d = os.path.join(a.save_run, now.strftime("%Y-%m-%d_%H%M"))
        os.makedirs(d, exist_ok=True)
        json.dump(board, open(os.path.join(d, "board.json"), "w"), indent=1)
        open(os.path.join(d, "card.txt"), "w").write(text + "\n")
        print(f"\n(saved {d}/board.json + card.txt)")
    if gates and not gates[0].passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
