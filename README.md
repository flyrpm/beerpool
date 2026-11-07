# Beer Pool

Weekly sweep for the BPN picks pool: prices every spread and total on the commissioner's
frozen sheet against the live multi-book market.

```bash
./run.sh "BP Wk Niner.pdf" "13-63,65-78"   # board PDF, open game-number ranges
```

- `vi_parse.py`: parses VegasInsider spread/total/moneyline tables (7 books + Kalshi + consensus).
- `analyze.py`: matches board games to market rows, de-vigs the 7-book median, and prices both
  sides of each spread and total **at the sheet number** (push = loss, with NFL/CFB key-number mass).
- `run.sh`: pdftotext → fetch → parse → analyze → ranked list. Writes `sweep.json`.
- `boards/`: archived board text by week.

Requires `pdftotext` (poppler-utils), `curl`, Python 3.
