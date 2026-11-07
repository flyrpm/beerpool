# Heady Topper Technologies — Week 10 forward evaluation

## State and scope

PR #1 was merged as `4019af5d2f350b5656f517754a586675844ca0ce` after
61 tests passed across Python 3.10–3.13, with no conflicts or unresolved critical
review findings. Production pricing, calibration and selection settings are unchanged.

The versioned `evaluation/baselines/ronnie-v1.json` pins the evaluation's exact
Git revision, source hashes, full frozen configuration/calibration, benchmark,
24-hour freshness policy, deadline policy and scoring/eligibility rules. The
baseline is public configuration only. Its pinned tooling/model revision is
`6411fe24f9f1dd4cd23398d12f9daa0e6b311816`, with manifest checksum
`34c0e939c58c25ef0d15c9434bc164b3e632b218e36e909316b8d7939806a1f3`. The manifest
is committed separately from the source revision to avoid a self-referential hash. Prediction records, sheets, original
snapshots, result exports and reports belong in **private durable storage**.
Default `data/predictions/`, `data/grades/` and `data/evaluation/` paths are ignored.

Do not fit, tune, replace calibration, change thresholds or choose variants from
prospective results. A new engineering revision requiring changed source files
needs an explicitly versioned new baseline; keep its results separate. Never
rewrite a previous baseline/entry. Commands use exclusive writes. Baseline/ledger
hashes detect accidental modification; they are not external timestamp attestation.

## Before November 14, 2026

1. Obtain the commissioner's actual Week 10 PDF and confirm the submission rule.
   Based on the existing rules, the expected main lock is **Saturday, November 14,
   2026 at noon Eastern (17:00 UTC)**. This is a planning assumption until checked
   against the actual commissioner instructions; do not quietly move a deadline.
2. Use the committed baseline, not a freshly refitted configuration. Work from
   the pinned revision or an otherwise identical source set. The wrapper verifies
   source bytes against both the manifest and its stated Git commit. Public
   manifest/documentation-only commits do not alter the frozen model sources.
3. Set up private storage and backups. Keep a copy of the baseline, repository
   checkout, PDF and all inputs there. Local exclusive files are not a substitute
   for durable backups or evidence of an actual pool submission.

The current repository contains Week 9 data only. No Week 10 selections have been
created, no scores have been invented, and no future snapshot has been scheduled
or claimed as captured. An operator must run the steps below at the appropriate
time. This document is not an installed automation.

## Capture and record before lock

Run from the repository root. Choose a private local directory (not a public Git
working tree); these example commands use an ignored directory as a staging area.
Back it up to your private durable storage.

```bash
PRIVATE="$PWD/data/evaluation/2026-week10"
mkdir -p "$PRIVATE" "$PWD/data/predictions" "$PWD/data/grades"
BASELINE="$PWD/evaluation/baselines/ronnie-v1.json"
```

Save the actual PDF as `$PRIVATE/week10.pdf`, then parse it using the existing
builder. No notes file is supplied: the preregistered evaluation compares Ronnie's
calibrated engine with raw market pricing; manual notes/MEGA are excluded for both.
The normal weekly live workflow can still be used separately, without changing it.

```bash
python3 build_board.py --pdf "$PRIVATE/week10.pdf" --cache "$PRIVATE/cache" \
  > "$PRIVATE/board.json"
```

Verify the parsed week, kickoff times, game numbers, home/away and sheet favorite/
spread/total against the original PDF, especially favorite flips. Set/confirm
`week` as `Week 10` in this input if no notes file supplied it. Verify
`default_lock` is `2026-11-14T12:00` Eastern. Do not use the existing Week 9 archive
or the newest available file merely because it exists. The builder's embedded
market is ignored by evaluation; only fresh captured snapshots price the record.

With enough time to resolve errors before lock (aim for 11:30 ET, not 11:59):

```bash
python3 snapshots.py take
python3 backtest/evaluation.py record \
  --baseline "$BASELINE" --board "$PRIVATE/board.json" \
  --snapshots data/snapshots --deadline 2026-11-14T12:00:00-05:00 \
  --season 2026 --week 10 --ledger data/predictions
```

Capture names are unique and published atomically. Recording uses only snapshots
whose capture AND receipt times are strictly before recording start, at most
24 hours old. The source hashes/configurations are frozen; no future or closing
odds fallback exists. Both cards use a single snapshot read set. The explicit
main deadline must equal the original board's default lock. Effective game locks
are min(main deadline, applicable board lock, kickoff), rechecked at recording
completion and after serialization/fsync immediately before publication.

The resulting `data/predictions/2026-wk10.json` includes both cards, every candidate
probability, sheet lines, full configuration, model/baseline/source/snapshot hashes,
coverage, decision/recording timestamps and game locks. A late record fails;
never backdate it. Run before earlier game locks if you want to include those
games. This baseline supports one weekly evaluation decision, not a later combined
card reconstructed from multiple early submissions.

Inspect both cards and coverage before declaring the recording complete. If either
has fewer than five legal picks, retain and report that gap; do not fabricate or
replace picks after lock. If errors prevent recording, report a missing week.
Publish/submit to the pool separately using its authorized process and retain the
actual submission receipt privately. The ledger does not submit picks.

## Report while games are pending

```bash
python3 backtest/evaluation.py report --baseline "$BASELINE" \
  --ledger data/predictions --season 2026 --weeks 10 \
  --output "$PRIVATE/report-pending.json" --markdown "$PRIVATE/report-pending.md"
```

If the week has not been recorded, the report says `not_recorded`, not a fabricated
card. If it is recorded, the report displays both cards and expected points;
actual results and the complete-week differential remain pending.

## Verify final results and grade

Obtain final scores from the original provider. Follow `docs/LEDGER.md` for exact
season/week/game/team/league/kickoff and final-score fields. Each final result in
this forward-reporting command additionally requires operator verification:

```json
"verification": {
  "source_url": "https://www.espn.com/college-football/game/_/gameId/ACTUAL_EVENT_ID",
  "event_id": "ACTUAL_EVENT_ID",
  "checked_utc": "ACTUAL_TIME_YOU_VERIFIED_THE_FINAL_SCORE"
}
```

These placeholders are schema guidance, not a result export. Use actual provider
IDs/URLs and timezone-qualified completion/verification times. Verification cannot
precede completion or be in the future. Final scores are nonnegative integers;
wrong identities or duplicate results fail closed. The command validates the
operator's evidence fields, not the provider URL contents: no network verification
is claimed. Retain the cited final response privately for audit. Missing,
postponed/canceled or nonfinal games remain ungraded. Pushes count as losses.

```bash
python3 backtest/evaluation.py report --baseline "$BASELINE" \
  --ledger data/predictions --results "$PRIVATE/verified-results.json" \
  --season 2026 --weeks 10 \
  --output "$PRIVATE/report-final-v1.json" --markdown "$PRIVATE/report-final-v1.md"
```

New finals/corrections get new result/report versions; commands never overwrite
existing artifacts. Grading uses frozen picks/probabilities and sheet numbers,
without rerunning pricing or reading current calibration. Report source and input
hashes are stored so calculations can be reproduced.

## Cumulative reporting

As new weeks arrive, retain the same baseline. Give a results export containing
all evaluated weeks and list the expected weeks, so unrecorded weeks stay visible:

```bash
python3 backtest/evaluation.py report --baseline "$BASELINE" \
  --ledger data/predictions --results "$PRIVATE/verified-results-to-date.json" \
  --season 2026 --weeks 10,11,12 \
  --output "$PRIVATE/cumulative-v1.json" --markdown "$PRIVATE/cumulative-v1.md"
```

Cumulative paired points/differential and expected points include only complete,
fully graded, prospective weeks whose baseline hash/configurations match exactly
and whose decision does not predate the baseline freeze. Historical records,
different baselines, incomplete cards and pending finals are displayed with
warnings and excluded from those totals. No selection among alternate records
is permitted. JSON preserves per-game coverage/parse warnings and detailed grades.

Engineering reliability means tested capture, deadline checks, provenance and
repeatable grading. Predictive performance requires enough independent future
weeks and an uncertainty analysis; a positive early point differential is not a
profitability or superiority finding. No monetary return, payout probability or
statistical significance is claimed by this report.
