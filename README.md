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
python3 backtest/extract_boards.py path/to/Beer_Pool_2026-27.xlsx > backtest/cache/boards.json
python3 backtest/fetch_results.py backtest/cache/boards.json > backtest/cache/results.json
python3 backtest/run_backtest.py backtest/cache/results.json path/to/Beer_Pool_2026-27.xlsx
```

Takes every board in the standings workbook (2026 Weeks A–9, plus last season's Weeks 10–21) and
matches each game on ESPN. It pulls final scores plus the opening and closing lines (DraftKings,
or ESPN BET when DK is missing). Every side is priced at the sheet number off the close and graded
with push = loss, and the engine's weekly card is compared with the pool's actual points.
The close comes after the Saturday-noon deadline, so treat the results as an upper bound.
Everything is cached in `backtest/cache/`, which is git-ignored because the workbook holds the
pool's private data.
