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

## Open questions / next steps

- **Huge-edge cap** (`HUGE_EDGE_P = 0.52`, off by default): +9 pts in 2025 and +10 in 2026 in
  the backtest, but the threshold was chosen after seeing the data. Turn it on once the
  pre-deadline snapshots confirm it.
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
