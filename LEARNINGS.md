# What we've learned (as of 2026 Week 9)

Evidence: 1,908 graded games across the full 2025 season and 2026 Weeks A–8. Each one has
the sheet line, the open and close (DraftKings or ESPN BET via ESPN) and the final score.
Every pick is graded at the sheet number, with push = loss.

**Big caveat on every number below:** the backtest prices picks off the *closing* line, which
forms after the Saturday-noon deadline and includes news we couldn't see. Treat the numbers as
an upper bound. The odds snapshots (Phase 1, running since Nov 7 2026) will give a clean test.

## Results

| | 2025 (22 wks) | 2026 (A–8) |
|---|---|---|
| Engine card | 232 pts, 63-44 (58.9%) | 115 pts, 31-14 (68.9%), would rank **2nd of 35** |
| Bert | 218 | 100, 26-19 (57.8%), 5th |
| Stein (2026 leader) | – | 118, 30-15 (66.7%) |
| Pool average | 8.8 / wk | 9.3 / wk, 49.7% |

Realistic expectation going forward: **57–60% picks, about 11 pts/week**, after discounting the
close-line lookahead. Coin-flipping scores 9.5 a week in this format, and the pool averages
about 9.

## What works

1. **The edge is the stale sheet versus the market, not football handicapping.** Picks the
   model grades 56%+ covered 63% (2025) and 67% (2026). Only the top of the ranking carries
   signal; picks graded 50–53% are coin flips.
2. **The size of the edge matters more than anything else:**

   | Sheet beats the close by | Model | Actual |
   |---|---|---|
   | ½ pt | 49.8% | 50.1% |
   | 1–1.5 | 51.6% | 53.2% |
   | 2–3 | 53.6% | **56.0%** |
   | 3.5+ | 57.7% | **50.8%** (59 picks) |

   Moderate edges outperform the model. Huge edges usually come from news (a QB injury) that
   the market has already priced, and they are coin flips.
3. **College is where the edge lives, especially early in the season.** NFL sheets track the
   market closely, while college lines (mismatches especially) move the most during the week.
4. **The hand-tuned key-number model is good.** An empirical model fitted on NFL results from
   2006–2021 did *not* beat it on 2022+ games it never saw (`margin_model.py eval`).
5. **Market moving against our side is a warning** (48–52% cover). It keeps its 3-point cap.

## What didn't

- **Totals edges are worth about half what the raw model says.** Totals use `TOTAL_SHRINK = 0.5`,
  fitted on 2025 only.
- **"Big unexplained move → 3-pt max" was backwards** when the move is toward us (51% vs 51% in
  2025, 63% in 2026). It is now a warning only.
- **Fable's market numbers were stale or single-book** (UCLA -5.5 was the open, not the market).
  Always use the live 7-book median.
- **Engine vs Bert, week by week:** the engine is steadier (9–16 every 2026 week). Bert's NFL
  picks beat it in weeks where the board had no college edges (2026 Week 1, Week 5).

## Improvements applied (Nov 7 2026)

1. **Calibration layer** (`models/calibration.json`, built by
   `run_backtest.py --no-fit --train 0 --save-calibration`). Each pick's probability is set by
   what that *type* of pick (spread or total) with that *size* of edge actually did
   historically, shrunk toward the model with 40 pseudo-picks. The model still orders picks
   within a bucket. It replaces the hand-set totals shrink and makes the huge-edge cap
   unnecessary (3.5+ edges now calibrate to 55% spreads / 57% totals instead of 59–60%).
   Current table: spreads 1–1.5 → 54.8%, 2–3 → 58.6%; totals 1–1.5 → 51.9%, 2–3 → 53.6%.
2. **5-point sweet-spot rule.** The two 5-pointers must be spreads with a 1.5–3 point edge,
   falling back to the old rules only if fewer than two exist.

Held-out test (calibration fitted on 2025, scored on 2026): current engine 115 pts (31-14) →
calibration 119 → **calibration + 5-pt rule 123 (33-12, 73.3%)**. 2025, in-sample: 232 → 256.
The 5-pt thresholds came from looking at both seasons, so part of that gain is in-sample.
Refit the calibration each time a season's results are added.

## Week 9 post-mortem (Nov 7 2026) — full write-up: [docs/postmortems/2026-week09.md](docs/postmortems/2026-week09.md) — the engine's own card lost both 5-pointers

The card Bert sent was the engine's card, unchanged:
`1. 37 MRSH +10.5 (p .600) · 2. 55 MICH -12.5 (.595) · 3. 63 WYO +6.5 · 4. 61 UTEP +9.5 · 5. 58 NMSU +17.5`.
Marshall lost 49-13; Michigan's offense was shut out by MSU. Tennessee -5.5 (a 1-pt edge and a
direct swing against Stein's Kentucky +5.5) won 34-6 but never made the card.

What went wrong, in the code:
1. **Pick 1 was a double-digit dog whose whole edge was an unexplained 3-pt line move.** The
   charter already banned that from 5-point slots; nothing in the code enforced it.
2. **Three of five picks rested on unverified line moves** (MRSH, WYO, UTEP; notes literally say
   "cause unverified"). The Nov 7 change made `big_move` a warning only, based on the backtest.
3. **Suspected lookahead in that backtest finding.** The backtest measures the move to the
   *close*, and the close includes Saturday news we can't see at noon. A pick whose line moved
   our way by close looks great in the backtest precisely because the news that moved it was
   real. At noon, an unexplained move toward a big dog is a coin flip at best. Re-test
   `big_move` on the odds snapshots (noon lines) before trusting it again.

Fix shipped (engine v2): the Three Locks live in the engine itself (`Config.charter`,
`five_bans`, `gate_card` in `beerpool.py`), so the card the engine builds and the card a human
or another model proposes go through the same rules. v1 stays frozen for the Week 10 test and
runs from a pinned checkout. 5-point slots are banned for spread dogs of +10 or more, picks
under 54%, unverified big moves and the existing 5-flags; slots are ordered by probability; any
card (engine, another model, or a gut swap) must print `GATE: PASS` before it is sent.
Replayed on Week 9 the gated card is `MICH / USA +8.5 / MRSH / WYO / UTEP` — Marshall drops to a
3 slot. The gate is a floor, not a model fix: it would have saved ~2 points, not the week.

Open: the engine still rates double-digit dogs with unexplained moves at 58–60%. Next step is
the snapshot re-test above, then decide whether `big_move` toward a +10 dog caps at 3 again.

## Open questions / next steps

- **Huge-edge cap** (`HUGE_EDGE_P`, off): superseded by the calibration layer; kept for
  comparison in the backtest.
- **Spreads of 21+ points** in the engine's card won only 54% (37 picks), against 62–68% for
  smaller spreads. Watch it; no rule yet.
- **Phase 4:** pool simulator. Use the standings, payouts and 34 entrants' histories to maximize
  the chance of finishing in the money.
- **Phase 2:** sharp-book anchor (Pinnacle or Circa) needs a paid odds feed.
- **Phase 5:** line-move model, once a season of snapshots exists.

## Tools

- `./run.sh` – this week's card (live lines + notes).
- `python3 backtest/run_backtest.py --pool 2025=… --pool 2026=…` – full backtest: fit on 2025,
  test on 2026, compare baseline / tuned / tuned+cap.
- `python3 backtest/replay_week.py --season 2026 --week 5 --workbook … [--cap]` – one week's
  replay next to Bert's card.
- `python3 snapshots.py at "2026-11-07T11:30"` – market as of a moment (cloud-scheduled snapshots).
- `python3 margin_model.py eval` – re-check the margin model each off-season.
