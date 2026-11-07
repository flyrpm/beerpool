# Data lake, live card and context

Added after the ronnie-v1 freeze. Everything here lives in **new files**, so none of the
seven sources pinned by `evaluation/baselines/ronnie-v1.json` changed and the baseline
still verifies (`evaluation.verify_baseline(..., check_sources=True)`).

## Storage: where private data lives

| Layer | Where | What |
|---|---|---|
| Raw, append-only | branch `data-lake` of this private repo, checked out at `data/lake/` | commissioner PDFs, standings workbooks, ESPN context pulls, ledger/grades/evaluation files. Each stored file has a `.meta.json` (sha256, source, received time). Duplicates are refused. |
| Odds snapshots | `data/snapshots/` on `main` | committed by the **GitHub Action** `.github/workflows/snapshots.yml` (no Claude usage, so no usage limits); the old Claude runner task is paused (backup only) |
| Query layer | `data/lake.db` (SQLite, git-ignored) | rebuilt from the two above with `python3 lake.py build` |

The `data-lake` branch survives container resets and stays private. It solves the
"private durable storage" gap in `docs/LEDGER.md`: point the ledger at it,
`--ledger data/lake/ledger/predictions`, then `python3 lake.py sync`.

```bash
python3 lake.py init                                     # once per checkout
python3 lake.py add-sheet "BP Wk Tenner.pdf" --season 2026 --week 10 \
    --message-id <gmail id> --received 2026-11-12T21:40:00Z
python3 lake.py add-email msg.json --season 2026 --week 10   # Gmail get_message RAW JSON
python3 lake.py build                                    # data/lake.db
python3 lake.py sql "select * from picks"
python3 lake.py sync                                     # commit + push data-lake
```

Tables: `files`, `teams` (ESPN ids), `sheet_games`, `odds` (every book, every snapshot,
with receipt time), `results` (finals + open/close), `picks` (archived live cards),
`context` (FPI, weather, injury counts).

## Live card (`live.py`, used by `run.sh`)

Prints the frozen engine's report unchanged, then adds two live-only pieces:

1. **Empty-card guard.** The exact optimizer returns no card when fewer than two picks are
   5-point eligible. The live card then shows a labelled THIN/FLAGGED fallback, five
   picks from distinct games with the best available in the 5-pt slots, as the charter
   requires. The ledger still records the engine's own (empty) card.
2. **Context section** (`context.py`), information only:
   - FPI win probability converted to an implied margin, flagged at 4+ points from the market
   - weather/indoor, flagged at gusts ≥15 mph or rain ≥50% (matters for totals)
   - NFL injury report, flagging a QB who is Questionable/Doubtful/Out
   - injury, suspension and QB headlines that name one of the game's teams

   College injury reports aren't published by ESPN, so headlines are the only signal there.
   No flag changes a probability or pick. After the Week 10 evaluation each flag can be
   backtested on the stored context and earn its way into a new baseline.

## Thursday sheet intake

**Not automated yet.** The plan: the existing "Beer pool daily picks tracker" scheduled
task (it has Gmail) runs `lake.py add-email` on Chris's line emails and `lake.py sync`.
Changing that task's instructions needs the owner's approval, which hasn't been given yet,
and new scheduled tasks can't be granted Gmail in this account. Until then, intake is
manual: any session with Gmail fetches the message (get_message, RAW), writes
`{id, raw}` to a file, then runs `lake.py add-email FILE --season S --week N` and
`lake.py sync`.
