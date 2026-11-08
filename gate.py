#!/usr/bin/env python3
"""Gate check on the FINAL card, whoever picked it (rules from docs/LESSONS_2026_WK09.md).

Every failure is one line with its cost; nothing is changed automatically -- the human
decides. Checks:
  G1  Pick 1 is the single highest-probability pick on the board.
  G2  No double-digit underdog in a 5-point slot.
  G3  No double-digit underdog with a bottom-30 offense anywhere on the card
      (offense rank comes from the weekly notes: tag `bottom30_offense`, or
      `offense_ok` once checked; a double-digit dog with neither is flagged as unverified).
  G4  Every pick has a probability of 52% or better.
  G5  Every line matches the pool PDF exactly.
  R4  When an alternative is within ~1% and the leader doesn't have it, flag the swing.
  R5  A 5-pointer needs both a number edge (1+ pt) and a football case
      (notes tag `football_case`); either alone is a 3-pointer.
Weekly notes may list the leader's card as `"leader_picks": ["48 UK +5.5", ...]`
(game number first); the game numbers are what's compared.
"""
from __future__ import annotations

import re

MIN_P = 0.52
TIE = 0.01            # "within about 1%"
DD = 10.0             # double-digit underdog: getting 10+ points


def _dog_points(c) -> float | None:
    return c.sheet_line if c.side not in ("OVER", "UNDER") and c.sheet_line > 0 else None


def leader_games(notes: dict | None) -> set[int]:
    out = set()
    for p in (notes or {}).get("leader_picks", []) or []:
        m = re.match(r"\s*(\d+)", str(p))
        if m:
            out.add(int(m.group(1)))
    return out


def leader_sides(notes: dict | None) -> dict[int, str]:
    """game -> the leader's pick text, to tell whether we're on his side of a game."""
    out = {}
    for p in (notes or {}).get("leader_picks", []) or []:
        m = re.match(r"\s*(\d+)\s+(.*)", str(p))
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def check(card: list, cands: list, notes: dict | None = None,
          pdf_lines: list[str] | None = None, five_bans=None) -> list[str]:
    """Returns gate lines: 'PASS ...' or 'FLAG ...' (each FLAG with its cost)."""
    out: list[str] = []
    if not card:
        return ["FLAG no card to check"]
    slot_pts = [5, 5, 3, 3, 3]

    # G1 -- Pick 1 is the board's best. With the charter gate's `five_bans`, "best" means
    # the best pick allowed in a 5-pt slot; a better pick the charter bars is reported as INFO.
    p1 = card[0]
    pool = [c for c in cands if not five_bans or not five_bans(c)] or cands
    best = max(pool, key=lambda c: c.p)
    top = max(cands, key=lambda c: c.p)
    if five_bans and top is not best and top.p > p1.p + 1e-9 and top.game != p1.game:
        out.append(f"INFO board's top pick {top.game} {top.label} ({top.p:.1%}) is barred from 5-pt slots "
                   f"by the charter ({'; '.join(five_bans(top))})")
    if best.p > p1.p + 1e-9 and best.game != p1.game:
        out.append(f"FLAG G1 Pick 1 {p1.game} {p1.label} ({p1.p:.1%}) is not the board's best: "
                   f"{best.game} {best.label} ({best.p:.1%}). Cost ~{5 * (best.p - p1.p):.2f} pts EV"
                   + (f"; engine held it out ({', '.join(sorted(best.tags))})" if best.tags else ""))
    else:
        out.append(f"PASS G1 Pick 1 {p1.game} {p1.label} is the board's best ({p1.p:.1%})")

    tags_of = lambda c: c.tags  # noqa: E731
    for i, c in enumerate(card):
        pts = slot_pts[i] if i < len(slot_pts) else 3
        dog = _dog_points(c)
        # G2 -- double-digit dog in a 5-pt slot
        if i < 2 and dog is not None and dog >= DD:
            out.append(f"FLAG G2 Pick {i + 1} {c.game} {c.label} is a double-digit dog in a 5-pt slot. "
                       f"Cost: 2 pts at risk vs a 3-pt slot (5 vs 3 if it loses); swap it to a 3-pt slot")
        # G3 -- double-digit dog + bottom-30 offense
        if dog is not None and dog >= DD:
            if "bottom30_offense" in tags_of(c):
                out.append(f"FLAG G3 Pick {i + 1} {c.game} {c.label}: double-digit dog with a bottom-30 offense "
                           f"(the Week 8-9 losing profile). Cost: {pts} pts at {c.p:.1%}; replace it")
            elif "offense_ok" not in tags_of(c):
                out.append(f"FLAG G3 Pick {i + 1} {c.game} {c.label}: double-digit dog, offense rank not "
                           f"verified. Check it (tag offense_ok or bottom30_offense in the notes)")
        # G4 -- probability floor
        if c.p < MIN_P:
            out.append(f"FLAG G4 Pick {i + 1} {c.game} {c.label} is {c.p:.1%}, under {MIN_P:.0%}. "
                       f"Cost ~{pts * (MIN_P - c.p):.2f} pts EV vs a {MIN_P:.0%} pick")
        # R5 -- 5-pointers need number edge + football case
        if i < 2:
            has_number = c.number_edge >= 1.0
            has_case = "football_case" in tags_of(c)
            if not (has_number and has_case):
                missing = " and ".join(x for x, ok in (("a number edge", has_number), ("a football case", has_case)) if not ok)
                out.append(f"FLAG R5 Pick {i + 1} {c.game} {c.label} lacks {missing}: a 3-pointer by rule 5. "
                           f"Cost: 2 pts at risk if it stays in a 5-pt slot")
    if not any(l.startswith("FLAG G4") for l in out):
        out.append(f"PASS G4 every pick is {MIN_P:.0%}+")

    # G5 -- lines vs the PDF
    if pdf_lines is not None:
        bad = [l for l in pdf_lines if not l.startswith("OK")]
        out += [f"FLAG G5 line not matched on the PDF: {l.strip()}" for l in bad] or \
               ["PASS G5 every line matches the PDF"]

    # R4 -- swing picks vs the leader
    lg, ls = leader_games(notes), leader_sides(notes)
    if lg:
        on_card = {c.game for c in card}
        for i, c in enumerate(card):
            same_side = c.game in ls and ls[c.game].split()[0].upper() == c.label.split()[0].upper()
            if not same_side:
                continue
            alts = [a for a in cands if a.game not in on_card and a.game not in lg
                    and abs(a.p - c.p) <= TIE]
            if alts:
                a = max(alts, key=lambda x: x.p)
                out.append(f"FLAG R4 Pick {i + 1} {c.game} {c.label} matches the leader; {a.game} {a.label} "
                           f"({a.p:.1%}, within 1%) is a swing pick he doesn't have")
        # Swing candidates: the other side of a leader pick at 50%+ (labelled if under the floor).
        swings = []
        for g, txt in ls.items():
            for a in cands:
                if a.game == g and a.side not in ("OVER", "UNDER") and \
                        a.label.split()[0].upper() != txt.split()[0].upper() and a.p >= 0.50 \
                        and a.game not in on_card and not txt.upper().split()[0].count("/"):
                    swings.append(a)
        for a in sorted(swings, key=lambda x: -x.p)[:3]:
            floor = "" if a.p >= MIN_P else f", under the {MIN_P:.0%} floor"
            out.append(f"INFO swing vs leader: {a.game} {a.label} ({a.p:.1%}{floor}), opposite his {a.game} {ls[a.game]}")
        shared = sum(1 for c in card if c.game in lg)
        out.append(f"INFO leader overlap: {shared} of {len(card)} games on our card are on the leader's card")
    return out


def section(card, cands, notes=None, pdf_lines=None, five_bans=None) -> str:
    lines = check(card, cands, notes, pdf_lines, five_bans)
    flags = sum(1 for l in lines if l.startswith("FLAG"))
    head = ("== GATE CHECK (final card) == " +
            (f"{flags} flag{'s' if flags != 1 else ''}: the human decides" if flags else "all checks pass"))
    return "\n".join([head] + ["  " + l for l in lines])
