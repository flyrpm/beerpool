#!/usr/bin/env python3
"""Live weekly card: the frozen engine's report + two live-only safeguards.

  python3 live.py board.json --pdf board.pdf [--now ISO] [--save-run runs] [--no-context]

Why a separate file: beerpool.py, build_board.py and the other pinned sources are
fingerprinted by the frozen `ronnie-v1` evaluation baseline (evaluation/baselines/).
Editing them would invalidate the Week 10 prospective evaluation. Everything here is
additive and only affects the card Bert actually sends:

1. Empty-card guard. The exact optimizer returns NO card when fewer than two picks are
   5-point eligible (e.g. every candidate carries qb_uncertain). The charter says a thin
   board still gets five picks, labelled honestly. The guard builds that labelled
   fallback; the frozen evaluation keeps recording its own (empty) card.
2. Context section (context.py): FPI, weather, NFL injuries, news flags for the card
   and the next-best candidates. Information only -- it never changes a pick.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beerpool as bp  # noqa: E402


def fallback_card(cands: list[bp.Candidate]) -> list[bp.Candidate]:
    """Five picks from distinct games when no legal 5-pt pair exists.

    5-pt slots take the two highest-probability picks from different games and settings
    (ignoring 5-pt flags, which is exactly why this is a labelled fallback); 3-pt slots
    take the next three distinct games. Thesis stacking is still avoided."""
    ranked = sorted(cands, key=lambda c: c.p, reverse=True)
    card, games, theses, envs = [], set(), set(), set()
    for slot in range(5):
        for c in ranked:
            if c.game in games or (c.thesis and c.thesis in theses):
                continue
            env = c.env or f"game{c.game}"
            if slot < 2 and env in envs:
                continue
            card.append(c)
            games.add(c.game)
            if c.thesis:
                theses.add(c.thesis)
            if slot < 2:
                envs.add(env)
            break
    return card


def guard(board: dict, now: datetime | None, cfg: bp.Config) -> tuple[list[bp.Candidate], list[str]]:
    """Returns (fallback card or [], notes). Empty list = the engine's card stands."""
    cands, _ = bp.build_candidates(board, now, [], cfg)
    card, _, _ = bp.build_card(cands, cfg=cfg)
    if card or not cands:
        return [], []
    fb = fallback_card(cands)
    notes = ["THIN / FLAGGED BOARD: the engine found no legal pair of 5-point picks "
             "(every strong candidate is 5-pt flagged). Fallback card below: best "
             "available picks, 5-point slots NOT up to the usual standard."]
    for i, c in enumerate(fb, 1):
        flags = ",".join(sorted(c.tags)) or "-"
        notes.append(f"  Pick {i} ({5 if i <= 2 else 3}) {c.game} {c.label:<26} p={c.p:.3f}  flags: {flags}")
    return fb, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--pdf")
    ap.add_argument("--now")
    ap.add_argument("--save-run", metavar="DIR")
    ap.add_argument("--no-context", action="store_true")
    a = ap.parse_args(argv)
    with open(a.board) as f:
        board = json.load(f)
    now = bp.parse_time(a.now or board.get("now")) or \
        datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    cfg = bp.Config.production()
    text = bp.report(board, now, a.pdf, cfg)

    fb, notes = guard(board, now, cfg)
    if fb:
        text += "\n\n== LIVE GUARD: FALLBACK CARD ==\n" + "\n".join(notes)
        text += "\n```\n" + bp.submission_block(board.get("week", "Week ?"), fb) + "\n```"
        if a.pdf:
            text += "\n" + "\n".join(bp.verify_against_pdf(fb, a.pdf))

    try:
        import charter_gate as cg
        gc, _ = bp.build_candidates(board, now, [], cfg)
        gcard = cg.charter_card(gc, cfg)
        text += "\n\n== FINAL CARD (charter-gated: send THIS one) ==\n"
        if gcard:
            block = bp.submission_block(board.get("week", "Week ?"), gcard)
            ok, rep = cg.check(block, gc)
            text += "```\n" + block + "\n```\n" + "\n".join(rep)
            if a.pdf:
                text += "\n" + "\n".join(bp.verify_against_pdf(gcard, a.pdf))
        else:
            text += "  THIN BOARD: no legal pair of 5-point picks under the charter."
        text += ("\n  Any other card: python3 charter_gate.py <board.json> --check card.txt "
                 "-> must print GATE: PASS before it is sent.")
    except Exception as e:  # the gate is mandatory; make a failure loud
        text += f"\n\n== FINAL CARD ==\n  CHARTER GATE ERROR: {e} -- do not send until fixed"

    if not a.no_context:
        try:
            import context
            cands, _ = bp.build_candidates(board, now, [], cfg)
            card, _, _ = bp.build_card(cands, cfg=cfg)
            picks = (fb or card) + [c for c in sorted(cands, key=lambda c: -c.p)
                                    if c not in (fb or card)][:5]
            text += "\n\n" + context.section(board, picks)
        except Exception as e:  # context is advisory; never block the card
            text += f"\n\n== CONTEXT ==\n  unavailable: {e}"

    print(text)
    if a.save_run:
        d = os.path.join(a.save_run, now.strftime("%Y-%m-%d_%H%M"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "board.json"), "w") as f:
            json.dump(board, f, indent=1)
        with open(os.path.join(d, "card.txt"), "w") as f:
            f.write(text + "\n")
        print(f"\n(saved {d}/board.json + card.txt)")


if __name__ == "__main__":
    main()
