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
from dataclasses import dataclass, fields
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beerpool as bp  # noqa: E402

FIVE_MIN_P = 0.54
CARD_MIN_P = 0.52
BIG_DOG = 10.0          # spread underdogs at +10 or more never take a 5-point slot
PICK1_TOLERANCE = 0.005


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


@dataclass
class GatedCandidate(bp.Candidate):
    @property
    def five_eligible(self) -> bool:  # type: ignore[override]
        return not five_bans(self)


def gated(cands: list[bp.Candidate]) -> list[GatedCandidate]:
    return [GatedCandidate(**{f.name: getattr(c, f.name) for f in fields(c)}) for c in cands]


def charter_card(cands: list[bp.Candidate], cfg: bp.Config) -> list[bp.Candidate]:
    """The engine's optimizer with the charter's 5-slot bans, slots then ordered by p."""
    g = gated(cands)
    card, _, _ = bp.build_card(g, cfg=cfg)
    if not card:
        return []
    fives = sorted(card[:2], key=lambda c: c.p, reverse=True)
    threes = sorted(card[2:], key=lambda c: c.p, reverse=True)
    return fives + threes


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
    return re.sub(r"\s+", " ", s.upper()).strip()


def match(cands: list[bp.Candidate], game: int, rest: str) -> bp.Candidate | None:
    """Find the candidate for a card line. Matches on game + side + line, so a spelled-out
    team name ('63 WYOMING +6.5') still matches the engine's '63 WYO +6.5'."""
    rest_n = _norm(rest)
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", rest_n)
    line = float(nums[-1]) if nums else None
    side_hint = "UNDER" if "UNDER" in rest_n else "OVER" if "OVER" in rest_n else None
    pool = [c for c in cands if c.game == game]
    for c in pool:
        if side_hint and c.side != side_hint:
            continue
        if not side_hint and c.side in ("OVER", "UNDER"):
            continue
        if line is not None and abs(abs(c.sheet_line) - abs(line)) > 1e-9:
            continue
        if not side_hint:
            want_sign = 1 if line is not None and line > 0 else -1
            have_sign = 1 if c.sheet_line > 0 else -1
            if line is not None and want_sign != have_sign:
                continue
            word = rest_n.split()[0]
            if not (word.startswith(c.side.upper()) or c.side.upper().startswith(word[:3])
                    or _norm(c.label).split()[0] == word):
                # last resort: only one side of the game has this sign
                pass
        return c
    return None


def check(card_text: str, cands: list[bp.Candidate]) -> tuple[bool, list[str]]:
    """Gate any proposed card. Returns (passed, report lines)."""
    lines, fails = [], []
    picks = parse_card(card_text)
    if len(picks) != 5:
        fails.append(f"card has {len(picks)} picks, needs 5")
    matched, games = [], set()
    for slot, game, rest in picks:
        c = match(cands, game, rest)
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
    eligible = [c for c in cands if not five_bans(c)]
    if eligible and matched:
        best = max(eligible, key=lambda c: c.p)
        p1 = next((c for s, c in matched if s == 1), None)
        if p1 is not None and p1.p + PICK1_TOLERANCE < best.p:
            fails.append(f"Pick 1 is {p1.game} {p1.label} (p={p1.p:.3f}) but the best "
                         f"5-eligible pick is {best.game} {best.label} (p={best.p:.3f})")
    fives = [c for s, c in matched if s <= 2]
    threes = [c for s, c in matched if s > 2]
    if fives and threes and max(c.p for c in threes) > min(c.p for c in fives) + PICK1_TOLERANCE:
        top3 = max(threes, key=lambda c: c.p)
        if not five_bans(top3):
            fails.append(f"{top3.game} {top3.label} (p={top3.p:.3f}) sits in a 3 slot but "
                         "outranks a 5-pointer")
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
        ok, rep = check(text, cands)
        print("\n".join(rep))
        sys.exit(0 if ok else 1)
    card = charter_card(cands, cfg)
    if not card:
        print("THIN BOARD: no legal pair of 5-point picks under the charter. Do not force one.")
        sys.exit(1)
    block = bp.submission_block(board.get("week", "Week ?"), card)
    ok, rep = check(block, cands)
    print("== FINAL CARD (charter-gated) ==")
    print("```\n" + block + "\n```")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
