# Beer Pool — lessons from Week 9 (Nov 7, 2026)

Context: 34-person picks pool. Picks 1-2 = 5 pts, 3-5 = 3 pts, pushes = losses.
We're 4th, 18 back of the leader with 12 weeks left. Goal = 1st place.

## What happened

- Sent card: MRSH +10.5 (Pick 1), MICH -12.5 (Pick 2), WYO +6.5, UTEP +9.5, NMSU +17.5.
- Marshall lost 49-13. Michigan's offense scored 0. Both 5-pointers lost.
- Tennessee -5.5 was on our analysis cards and won 34-6, but it didn't make the sent card.
  It was also a swing pick against the leader (Stein had Kentucky).

## Root causes

1. Too many cards. By 10 AM there were four versions (first draft, revision after
   model pushback, a 2-college/3-NFL split, and a 31-game theses doc). No single FINAL card.
2. No rule check on the card as sent. Two double-digit dogs with weak offenses got on,
   one at Pick 1. This is the same losing profile as Florida +12.5 and GT +8.5 in Week 8.
3. Michigan was a real 2-point number edge that lost. That's variance, but its risk
   (120th-ranked offense, 3rd-string QB, 1-5 as a favorite) was flagged and still put in a 5 slot.

## Rules going forward (non-negotiable)

1. ONE FINAL card, delivered once. Revise only for new information (injury news, a real
   line move, a verified error). Never stack alternate cards; merge input into one card.
2. Gate check on the final card, whoever picked it:
   - Pick 1 = the single highest-probability pick on the board
   - No double-digit underdog in a 5-point slot
   - No double-digit dog with a bottom-30 offense anywhere on the card
   - Every pick has a stated probability of 52% or better
   - Every line matches the pool PDF exactly

   Any failure gets flagged in one line with its cost. The human decides.
3. Pick 1 is our leak: 4-6 on the season vs. the leader's 8-1. Pick 1 is never a lean,
   a story pick, or a big dog.
4. When two picks are within about 1%, take the side the leader DOESN'T have.
5. Prefer the pick where the number edge and the football case agree (Wyoming, Tennessee).
   A number edge alone is a 3-pointer. A football story alone is a 3-pointer.

## What worked

- Market sweep found real edges (WYO 2.5 pts, MICH 2 pts, TENN 1 pt).
- Leader's card was pulled before lock, so we knew TENN was a swing.
- Catching stale lines: Colts +5.5 c

> **[The source text was cut off here, mid-sentence. Finish this section.]**

---

## How the rules are enforced in code

`gate.py` runs on every live card (`run.sh` → `live.py`) and prints a **GATE CHECK**
section. Each failure is one line with its cost, and nothing is changed automatically:
the human decides.

| Rule | Check | How it's enforced |
|---|---|---|
| 1 | One final card | `live.py` labels its output the ONE final card ("revise only for new information"); every run is archived in `runs/<date_time>/` |
| 2 | Pick 1 = board's best | G1 compares Pick 1 with the highest-probability candidate on the board and states the EV cost |
| 2 | No double-digit dog in a 5-pt slot | G2 (dog getting 10+ points in slot 1 or 2) |
| 2 | No double-digit dog with a bottom-30 offense | G3: weekly notes tag the pick `bottom30_offense` (replace it) or `offense_ok` (checked); a double-digit dog with neither tag is flagged as unverified |
| 2 | Every pick ≥ 52% | G4 |
| 2 | Lines match the PDF | G5 (from the existing PDF verification) |
| 3 | Pick 1 never a lean, story or big dog | G1 + G2 + R5 together on slot 1 |
| 4 | Within ~1%, take the side the leader doesn't have | R4 flags a card pick that matches the leader when an off-card pick within 1% doesn't; INFO lists swing picks opposite the leader's card and our overlap with it. The leader's card goes in the weekly notes as `"leader_picks": ["48 UK +5.5", ...]` |
| 5 | 5-pointers need number edge + football case | R5: a 5-pointer needs a 1+ point edge **and** the notes tag `football_case`; either alone gets flagged as a 3-pointer |

Replaying the Week 9 card (9:48 ET market, Stein's card as the leader) through the gate
flags Marshall +10.5 at Pick 1 (G2), both 5-pointers for no stated football case (R5),
and the two double-digit dogs' offenses as unverified (G3). It also lists
Tennessee -5.5 as a swing against Stein's Kentucky. By then the market had moved to
-6, so the model priced it at 50.2%, under the 52% floor, and it is labelled that way.

These rules sit in the live layer. The frozen `ronnie-v1` evaluation baseline and its
pinned files are unchanged.
