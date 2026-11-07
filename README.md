# Beer Pool

Builds Ronnie's weekly card for the BPN picks pool. The commissioner's sheet is a frozen
snapshot; the market keeps moving. The tool finds where the sheet number beats the live
market, prices every side **at the sheet number** (push = loss), layers the week's football
notes on top, and builds the card under the pool rules.

```bash
./run.sh                                   # newest BP*.pdf in ~/Downloads + newest notes/*.json
./run.sh ~/Downloads/"BP Wk Niner.pdf" notes/2026-wk09.json
NOW=2026-11-07T09:00 ./run.sh              # pretend it's a given time (lock checks)
python3 -m unittest test_beerpool          # tests
```

See **LEARNINGS.md** for what the backtests have shown so far.

## Pipeline

| Step | File | What it does |
|---|---|---|
| Board | `build_board.py` | Parses the PDF (game #, kickoff, sheet favourite/line/total). |
| Market | `build_board.py`, `vi_parse.py` | Pulls VegasInsider: median of 7 books (bet365, MGM, DK, Caesars, FanDuel, Hard Rock, Fanatics; Kalshi excluded), juice at the median line, opening line, moneylines for spreads of 3.5 or less. Team abbreviations from ESPN. |
| Locks | `beerpool.py` | Games before Saturday noon ET lock at kickoff; everything else locks Saturday noon. |
| Pricing | `beerpool.py` | Fits a margin / total distribution with key-number mass (NFL 3/7/10/14…, CFB 3/7/10/14/17…) to the de-vigged market, then prices each side at the sheet number. A sheet -3 plays like -3.5. |
| Flags | `beerpool.py` | **No call** if the books disagree by more than 1 point on a spread (1.5 on a total), ignoring one stale book at each end. **3-point max** for `big_move` (3+ points since open, cause unverified), `steam_against` (market moved 2+ points away from the side), `qb_uncertain`, `starter_uncertain` and `model_only`. |
| Card | `beerpool.py` | Highest probabilities go to the 5-point slots if they're eligible. One pick per game, no shared thesis, 5-pointers in different environments, no Dallas, "thin board" warning under 53%. |
| Output | `beerpool.py` | Submission block, MEGA EV (10p − 5; it only fires if `mega` is set in the notes), and every pick checked against the PDF text. |

## Weekly notes (`notes/YYYY-wkNN.json`)

The football layer. Keyed by game number, then side (the team abbreviation as it prints on
the card, or `OVER` / `UNDER`):

```json
{"week": "Week 9", "mega": null,
 "games": {"55": {"MICH": {"adj": 0.015, "note": "MSU 13 out; QB questionable"}},
           "63": {"WYO":  {"clear_tags": ["big_move"], "note": "UNLV QB ruled out (verified)"}}}}
```

- `adj`: probability nudge. Keep it within ±0.02.
- `tags` / `clear_tags`: add or remove flags. Use `clear_tags` once the cause of a big move is verified.
- `thesis` / `env`: stop one idea from being stacked across picks.
- `mega`: `{"game": 49}` fires the MEGA on that game.

Requires `pdftotext` (poppler-utils) and Python 3.9+. Nothing to pip install.

## Backtest

```bash
python3 backtest/extract_boards.py BP-Week_21.xlsx Beer_Pool_2026-27.xlsx > backtest/cache/boards.json
python3 backtest/fetch_results.py backtest/cache/boards.json > backtest/cache/results.json
python3 backtest/run_backtest.py --pool 2025=BP-Week_21.xlsx --pool 2026=Beer_Pool_2026-27.xlsx [--cards]
```

Takes every board in the standings workbook (2026 Weeks A–9, plus last season's Weeks 10–21) and
matches each game on ESPN. It pulls final scores plus the opening and closing lines (DraftKings,
or ESPN BET when DK is missing). Every side is priced at the sheet number off the close and graded
with push = loss, and the engine's weekly card is compared with the pool's actual points.
The close comes after the Saturday-noon deadline, so treat the results as an upper bound.
Everything is cached in `backtest/cache/`, which is git-ignored because the workbook holds the
pool's private data.

Tuning is fitted on one season (`--train`, default 2025) and reported on the other (`--test`, 2026).
Results as of Week 9, 2026 (1,908 games):

| | 2025 (22 wks) | 2026 (A–8) |
|---|---|---|
| Engine card, pts/week | 10.95 | 12.44 |
| Bert, pts/week | 9.91 | 11.11 |
| Pool average, pts/week | 8.83 | 9.34 |
| Model ≥56% picks covered | 63% | 67% |
| All positive-edge sides covered | ~51% | ~56% |

Only the top of the ranking carries signal. Mid-range "edges" are close to coin flips, and
totals edges are worth about half what the raw model says (`TOTAL_SHRINK = 0.5`).

## Odds snapshots (Phase 1 of the redesign)

`snapshots.py take` saves every book's spread, total and moneyline for the NFL and college slates
to `data/snapshots/YYYY-MM-DD/<UTC HHMM>_<league>.json.gz`. A cloud scheduled task runs it
Thu/Fri/Sat/Sun at 8:13, 11:13, 18:13 and 21:13 ET and commits the files, so `git pull` brings
them down. `snapshots.py build-db` builds `data/odds.db` (SQLite) from them, and
`snapshots.py at "2026-11-07T11:30"` shows the market as it stood before the noon lock.
`./schedule_mac.sh install` runs the same job on the Mac instead, as a fallback.

## Margin model check (Phase 3)

`python3 margin_model.py eval` downloads nflverse's results and closing lines (1999 to now),
fits an empirical "P(margin | closing spread)" model on 2006–2021, and scores it against the
engine's hand-tuned key-number model on 2022+ games it never saw. As of Nov 2026 the hand-tuned
model wins on both spreads (Brier 0.2433 vs 0.2435–0.2438) and totals (0.2465 vs 0.2472–0.2475),
so the engine keeps it. NFL totals spread of 13 also beat Fable's 10.5 on the same test.
Re-run it each off-season.

## Engine settings, reproducibility, team identity

- **Settings:** every tunable lives in `beerpool.Config`. Live cards use `Config.production()`
  (calibration table plus the 5-pt sweet-spot rule), and `--legacy` reproduces the first merged
  engine. The backtest builds one `Config` per variant, so variants can't leak into each other.
- **Run archive:** each `./run.sh` saves `runs/<date_time>/board.json` + `card.txt`. The card
  header shows the market timestamp and the settings that produced it.
- **Team identity:** `teams.py` resolves every source's spelling to an ESPN team id
  (`models/teams.json`, refreshed with `python3 teams.py refresh`). FBS/FCS programs win over
  lower-division namesakes, and it never guesses: an ambiguous name returns None with a reason.
  The live board and backtest matchers will move onto it next. (A first try at the backtest
  matcher dropped 21 games; parked until the tier fix is verified.)

## Exact selection and snapshot-only replay

Card selection now searches legal slot assignments exactly, preserving the five-point
sweet-spot preference, and maximizes expected pool points within those constraints.
The weekly `./run.sh` command stays the same. An independent offline replay command
freezes settings and uses only pre-submission snapshots, reporting missing observations
without substituting closing odds. See [Phase 2 implementation](docs/PHASE_2_IMPLEMENTATION.md)
for commands, behavior changes and evidence limitations.

## Frozen forward evaluation

The opt-in [predictions ledger](docs/LEDGER.md) freezes weekly Ronnie and raw-market
benchmark cards before the deadline, then grades explicit final results without
rerunning pricing. It keeps missing observations/results visible, rejects late
prospective records, and never fits probabilities. GitHub Actions runs the full
unit suite on pushes and pull requests. The live weekly command stays unchanged.
