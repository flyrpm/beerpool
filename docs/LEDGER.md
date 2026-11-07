# Frozen weekly evaluation ledger

This adds forward evaluation, not another model variant to tune. The live `run.sh`
workflow, probabilities, production calibration table and thresholds are unchanged.
The ledger is an opt-in **evaluation card**, not proof of an actual pool submission.
Manual notes/MEGA are excluded for both variants, just as in snapshot replay.

## Weekly procedure

Before the first evaluation week, freeze the configuration and retain that file for
subsequent weeks. Do not refit or replace it in response to the evaluation results.
Use the same source revision: replay rejects mismatched source hashes.

```bash
python3 backtest/snapshot_replay.py freeze --output frozen-evaluation.json
```

Before the submission deadline, take fresh odds snapshots, prepare the sheet board
using the existing workflow, and record the week:

```bash
python3 snapshots.py take
python3 backtest/predictions_ledger.py record \
  --board board.json --config frozen-evaluation.json \
  --snapshots data/snapshots --deadline 2026-11-14T12:00 \
  --season 2026 --week 10 --max-age-hours 24 --ledger data/predictions
```

Use the actual week/deadline. A naive timestamp means Eastern; explicit offsets
are supported. Prediction information is cut off at **recording start**, not the
later submission deadline. No CLI backdating option exists. Recording and saving
a prospective entry must happen before the earliest applicable submission/game lock
and before predicted games kick off. Per-game effective locks are frozen in the
entry and rechecked after serialization/fsync, immediately before atomic publication. Earlier-locked games are excluded; the initial foundation supports one
submission per week, not multiple early-game decisions. `--historical` explicitly
labels past scenarios; they must never be pooled with prospective evidence.

The sheet board needs unique game numbers, full names for snapshot matching,
league, home/away abbreviations, original kickoff and sheet lines. Missing kickoff
is an error; missing markets/names remain visible coverage gaps. Embedded board
markets, manual notes and outcomes are not prediction inputs. Correct sheet
orientation and submission rules remain the operator's responsibility.

New `snapshots.py take` captures add timezone-qualified `received_utc` after fetching
and parsing. Prospective ledger entries reject selected legacy captures with no
receipt timestamp. Capture filenames include microseconds and a random ID; exclusive atomic publication
prevents overwrite even if both clock and ID collide. Existing snapshot files remain
unchanged and historical replay
can still inspect them. A positive finite age limit is required for the ledger;
choose and hold this data-quality policy fixed before evaluation.

## What is frozen

Each `SEASON-wkWEEK.json` contains:

- Recording time, decision time, submission deadline, season/week and prospective/
  historical label, game identity and kickoff metadata.
- Deep-copied Config/calibration, replay source hashes, ledger source hash, input
  board hash, chosen snapshot hashes/timestamps, coverage and parse errors.
- All candidate probabilities and sheet lines, each selected card's slot/weight,
  and frozen expected points for Ronnie and the benchmark.
- A canonical SHA-256 checksum of the complete payload, verified before grading.

Writes are atomic and exclusive, with one file per season/week. Existing entries cannot be
silently overwritten by the command. This guards accidental edits; it is **not** a
signed, independently timestamped or tamper-proof registry. Keep private backups
of entries, original sheet, frozen config, raw snapshots and actual submissions.
The repository ignores default ledger/grade directories to avoid accidentally
publishing private weekly data. No real prospective week was fabricated for tests.

## Benchmark definition

The benchmark uses existing market-implied distributions priced at the sheet,
with pushes losing. Calibration is disabled, spread/total shrink both equal 1,
and the optional huge-edge probability cap is disabled. These are explicit
benchmark settings; production settings are not changed. Market input, candidate
universe, game/thesis/environment rules and five-point sweet-spot policy remain
the same. Thus the comparison primarily evaluates the calibration layer under
one shared selection policy, not a completely different handicapping strategy.
No benchmark parameters are fitted or selected from subsequent outcomes.

## Actual-results grading

Supply a JSON array of results with exact ledger game identities; for example:

```json
[
  {
    "season": 2026, "week": "10", "game": 55, "league": "CFB",
    "away": "MSU", "home": "MICH", "kickoff": "2026-11-14T19:30",
    "status": "final", "home_score": 24, "away_score": 20,
    "completed_utc": "2026-11-15T04:00:00Z"
  }
]
```

The example is a schema illustration, not an actual result. Obtain verified scores
from the original results provider and retain that input. This initial command
accepts an explicit results export; it does not fetch ESPN, consult closing odds,
or attempt ambiguous fuzzy matching. Other weeks are ignored, duplicate results
within a week are rejected, and home/away/league/kickoff mismatches fail closed.
Scores must be nonnegative integers. Completion time must be timezone-qualified,
after kickoff and no later than grading time. Only `status: final` is graded.
Missing, postponed and canceled games stay pending, not losses.

```bash
python3 backtest/predictions_ledger.py grade \
  --entry data/predictions/2026-wk10.json --results actual-results.json \
  --output data/grades/2026-wk10-v1.json
```

Create the output directory first. Grade reports are also exclusively created;
write a new version for later finals/corrections. The original ledger never changes.
Grading reads frozen predictions and works without the original pricing sources,
configuration files, snapshots or network. It reports:

- Wins/pushes, graded/pending counts and actual pool points.
- Frozen expected points and expected points on only the graded picks.
- Card and all-candidate Brier/log-loss summaries.
- Snapshot coverage, per-pick results and result-input issues/hash.
- Ronnie minus benchmark points **only when both have five picks and all ten
  selected slots have final results**. Partial weekly scores are not treated as
  comparable complete weeks.

Pushes count as losses for spreads/totals. There is no MEGA, monetary ROI, payout
simulation or automatic void/replacement policy. Candidate metrics share game
outcomes and are not independent observations. A pre-game timestamp does not prove
training data independence: the committed calibration uses old inspected seasons.
Prospective weeks should be evaluated separately, without changing rules midstream.

## Verification

`python3 -m unittest discover -v` covers the original engine/optimizer/replay plus
ledger immutability, missing/future/invalid results, final-score identity validation,
push losses, benchmark settings, receipt requirements, deadline checks and
nonmutating reproducible grading. GitHub Actions runs the full suite on Python
3.10–3.13 for pushes and pull requests. CI success checks software behavior; it is
not proof of predictive edge or profitability.

## Merge review hardening

Replay hashes the exact compressed bytes it parses, without a second filesystem
read. Ronnie and the benchmark share a single in-memory snapshot read set and
separate detached configurations. Receipts earlier than capture and truncated
gzip files become explicit input errors. The snapshot inspection command chooses
by payload availability time, including receipt, rather than filename order.
Grading reports fingerprint the grader source in addition to the results and
ledger hashes. Existing manifests from a different replay source revision still
require their original checkout; create a new manifest before starting a new
evaluation, without refitting the calibration table.
