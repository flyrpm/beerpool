#!/usr/bin/env python3
"""Charter gate: the Three Locks Bert set after Week 9, enforced in code.

  python3 charter_gate.py runs/<run>/board.json                 # build the gated FINAL card
  python3 charter_gate.py runs/<run>/board.json --check card.txt  # GATE: PASS / FAIL on any card

Why: Week 9's sent card was the engine's own card. Pick 1 was MRSH +10.5 and Pick 4 was
UTEP +9.5 -- double-digit-ish dogs whose "edge" was an unexplained 3-4 point line move.
Both lost badly (49-13; ...). The charter already said "no double-digit dog in a 5 slot" and
"no 5-pointer on an unverified cause", but nothing in the code enforced it. This file does.

Additive only: beerpool.py and the other files pinned by the ronnie-v1 baseline are untouched,
so the frozen evaluation keeps recording the engine's own card.

THE THREE LOCKS
1. Slots are assigned by probability: highest eligible = Pick 1, next = Pick 2.
2. 5-point slots are banned for: underdogs of +10 or more; picks under 54%; any pick with
   an unverified big line move (big_move tag not cleared in the notes); anything the engine
   already 5-flags (qb_uncertain, starter_uncertain, model_only, steam_against, huge_edge).
   No override for the 5-point slots.
3. Nothing is sent without GATE: PASS. Every pick needs >= 52%, lines must match the board,
   one pick per game, no Dallas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from itertools import combinations
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beerpool as bp  # noqa: E402

FIVE_MIN_P = 0.54
CARD_MIN_P = 0.52
BIG_DOG = 10.0          # spread underdogs at +10 or more never take a 5-point slot
PROB_EPS = 1e-12


def five_bans(c: bp.Candidate) -> list[str]:
    """Reasons this candidate may not occupy a 5-point slot (empty = allowed)."""
    why = []
    if c.side not in ("OVER", "UNDER") and c.sheet_line >= BIG_DOG:
        why.append(f"dog +{c.sheet_line:g} (>= +{BIG_DOG:g})")
    if c.p < FIVE_MIN_P:
        why.append(f"p={c.p:.3f} < {FIVE_MIN_P}")
    if "big_move" in c.tags:
        why.append("unverified big line move")
    engine = sorted(c.tags & bp.NO_FIVE_TAGS - {"big_move"})
    if engine:
        why.append("flag: " + ",".join(engine))
    return why


def compatible(candidate, chosen):
    return all(candidate.game != other.game and
               not (candidate.thesis and candidate.thesis == other.thesis)
               for other in chosen)


def charter_card(cands: list[bp.Candidate], cfg: bp.Config) -> list[bp.Candidate]:
    """Maximize five-slot probability first, then total expected points on a full card."""
    ranked = sorted((c for c in cands if c.p >= CARD_MIN_P and c.side not in bp.BANNED_TEAMS),
                    key=lambda c: -c.p)
    eligible = [c for c in ranked if not five_bans(c)]
    pairs = sorted(combinations(eligible, 2), key=lambda pair: -(pair[0].p + pair[1].p))
    best, best_pair, best_rest = [], -1.0, -1.0
    for a, b in pairs:
        pair_p = a.p + b.p
        if pair_p < best_pair - PROB_EPS:
            break
        if not compatible(b, [a]) or (a.env or f"game{a.game}") == (b.env or f"game{b.game}"):
            continue
        rest = [c for c in ranked if compatible(c, [a, b])]
        for x, y, z in combinations(rest, 3):
            rest_p = x.p + y.p + z.p
            if rest_p <= best_rest + PROB_EPS:
                continue
            if compatible(y, [x]) and compatible(z, [x, y]):
                best, best_pair, best_rest = [a, b, x, y, z], pair_p, rest_p
    return best


def final_section(board: dict, cands: list[bp.Candidate], cfg: bp.Config,
                  pdf: str | None = None) -> tuple[bool, str]:
    """The sendable FINAL card, or a loud DO NOT SEND. Never both."""
    card = charter_card(cands, cfg)
    if not card:
        return False, ("== FINAL CARD: NONE -- DO NOT SEND ==\n  No complete card passes the "
                       "charter (need 5 picks >= 52% and two legal 5-pointers). Thin board: "
                       "build by hand and run --check.")
    block = bp.submission_block(board.get("week", "Week ?"), card)
    ok, rep = check(block, cands, board)
    if not ok:
        return False, ("== FINAL CARD: GATE FAILED -- DO NOT SEND ==\n" + "\n".join(rep))
    text = "== FINAL CARD (charter-gated, GATE: PASS -- send THIS one) ==\n```\n" + block + "\n```\n" + "\n".join(rep)
    if pdf:
        text += "\n" + "\n".join(bp.verify_against_pdf(card, pdf))
    return True, text


LINE_RE = re.compile(r"^\s*(\d)\.\s*(\d+)\s+(.+?)\s*$")


def parse_card(text: str) -> list[tuple[int, int, str]]:
    """'1. 37 MRSH +10.5' -> (slot, game, rest). Ignores headers and Mega-Pick suffix."""
    out = []
    for line in text.splitlines():
        m = LINE_RE.match(line.replace("`", ""))
        if m:
            rest = re.sub(r"\s*mega-?pick\s*$", "", m.group(3), flags=re.I)
            out.append((int(m.group(1)), int(m.group(2)), rest))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9/+\-. ]", " ", s.upper())).strip()


def _side_names(board: dict | None, game: int) -> dict[str, list[str]]:
    """side abbr -> accepted spellings (abbr, full sheet name, and its unique words)."""
    if not board:
        return {}
    g = next((g for g in board.get("games", []) if g.get("num") == game), None)
    if not g:
        return {}
    out = {g["away"]: [g["away"]], g["home"]: [g["home"]]}
    names = g.get("names") or ""
    parts = re.split(r"\s+at\s+", names, maxsplit=1)
    if len(parts) == 2:
        for side, nm in ((g["away"], parts[0]), (g["home"], parts[1])):
            out[side].append(_norm(nm))
    return out


def side_matches(token: str, side: str, game: int, board: dict | None) -> bool:
    """Verified team identity: the card's team text must be the side's abbreviation or its
    sheet name (spelled-out names like WYOMING / TENNESSEE are allowed). Nothing else."""
    tok = _norm(token)
    if tok == side.upper():
        return True
    names = _side_names(board, game)
    if side not in names:
        return False
    if tok in names[side][1:]:
        return True
    # A unique word of this side's sheet name (TITANS for 'Tennessee Titans'), but only if
    # the other team's name doesn't contain it ('MICHIGAN' must not match Michigan State).
    other = [n for s2, ns in names.items() if s2 != side for n in ns[1:]]
    mine = [n for n in names[side][1:]]
    hit = any(re.search(rf"\b{re.escape(tok)}\b", n) for n in mine)
    clash = any(re.search(rf"\b{re.escape(tok)}\b", n) for n in other)
    return hit and not clash and len(tok) >= 4


LINE_TAIL = re.compile(r"^(?P<team>.*?)\s*(?P<line>[-+]?\d+(?:\.\d+)?)$")


def match(cands: list[bp.Candidate], game: int, rest: str,
          board: dict | None = None) -> bp.Candidate | None:
    """Find the candidate for a card line. Requires an explicit line that equals the sheet
    line from that side's view, and a verified team identity (spreads) or OVER/UNDER."""
    m = LINE_TAIL.match(_norm(rest))
    if not m:
        return None
    team, line = m.group("team").strip(), float(m.group("line"))
    words = team.split()
    for c in cands:
        if c.game != game:
            continue
        if c.side in ("OVER", "UNDER"):
            if c.side in words and abs(c.sheet_line - abs(line)) < 1e-9:
                return c
            continue
        if "OVER" in words or "UNDER" in words:
            continue
        signed = line if re.search(r"[-+]\d", rest) else None
        if signed is None or abs(c.sheet_line - signed) > 1e-9:
            continue
        if side_matches(team, c.side, game, board):
            return c
    return None


def check(card_text: str, cands: list[bp.Candidate],
          board: dict | None = None) -> tuple[bool, list[str]]:
    """Gate any proposed card. Returns (passed, report lines)."""
    lines, fails = [], []
    picks = parse_card(card_text)
    slots = [p[0] for p in picks]
    if slots != [1, 2, 3, 4, 5]:
        fails.append(f"slots must be 1-5 exactly once and in order (got {slots or 'none'})")
    matched, games = [], set()
    for slot, game, rest in picks:
        c = match(cands, game, rest, board)
        if c is None:
            fails.append(f"Pick {slot}: '{game} {rest}' not found on the board at that line "
                         "(typo, wrong side, or game locked)")
            continue
        if game in games:
            fails.append(f"Pick {slot}: game {game} used twice")
        games.add(game)
        if c.side == "DAL":
            fails.append(f"Pick {slot}: Dallas pick (house rule)")
        if c.p < CARD_MIN_P:
            fails.append(f"Pick {slot}: {game} {c.label} p={c.p:.3f} < {CARD_MIN_P}")
        if slot <= 2:
            bans = five_bans(c)
            if bans:
                fails.append(f"Pick {slot} (5 pts): {game} {c.label} banned from 5 slots: "
                             + "; ".join(bans))
        matched.append((slot, c))
        lines.append(f"  Pick {slot} ({5 if slot <= 2 else 3}) {game} {c.label:<22} p={c.p:.3f}"
                     f"  flags: {','.join(sorted(c.tags)) or '-'}")
    for i, (sa, a) in enumerate(matched):
        for sb, b in matched[i + 1:]:
            if a.thesis and a.thesis == b.thesis:
                fails.append(f"Picks {sa} and {sb} share a thesis ({a.thesis})")
    five = [c for s, c in matched if s <= 2]
    if len(five) == 2 and (five[0].env or f"game{five[0].game}") == (five[1].env or f"game{five[1].game}"):
        fails.append(f"both 5-pointers are in the same environment ({five[0].env})")
    if len(five) == 2:
        if five[1].p > five[0].p + PROB_EPS:
            fails.append("Put the higher probability five-pointer in slot 1")
        preferred = charter_card(cands, bp.Config.production())
        if preferred and sum(c.p for c in preferred[:2]) > sum(c.p for c in five) + PROB_EPS:
            names = " / ".join(c.label for c in preferred[:2])
            fails.append(f"A stronger legal five-point pair can complete the card: {names}")
    exp = sum((5 if s <= 2 else 3) * c.p for s, c in matched)
    lines.append(f"  Expected points: {exp:.2f}")
    head = "GATE: PASS" if not fails else "GATE: FAIL"
    return not fails, [head] + [f"  x {f}" for f in fails] + lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--check", metavar="CARD_TXT", help="file with the card to gate ('-' = stdin)")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    with open(a.board) as f:
        board = json.load(f)
    now = bp.parse_time(a.now or board.get("now")) or \
        datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    cfg = bp.Config.production()
    cands, _ = bp.build_candidates(board, now, [], cfg)
    if a.check:
        text = sys.stdin.read() if a.check == "-" else open(a.check).read()
        ok, rep = check(text, cands, board)
        print("\n".join(rep))
        sys.exit(0 if ok else 1)
    ok, out = final_section(board, cands, cfg)
    print(out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
