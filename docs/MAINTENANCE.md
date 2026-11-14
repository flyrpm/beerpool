# BeerPool maintenance handoff

Status: maintenance mode through the first genuine Week 10 evaluation.

**Nov 8 2026 (Bert's decision): engine v2 on `main`, v1 frozen on a pinned checkout.** After
Week 9 the charter (Three Locks) was built into the engine (`Config.charter`, `gate_card`).
The `ronnie-v1` baseline is unchanged and records only from
`python3 backtest/evaluation.py pin ...` (newest commit whose engine files match its
fingerprint). Nothing below about v1 changes; it just runs from that checkout.
No additional feature development, refitting, probability/calibration/threshold
changes or selection-policy changes are authorized before that evaluation.
Operate the frozen `ronnie-v1` baseline. Report newly discovered critical defects
and NO-GO conditions; do not silently replace the baseline or weaken a gate.

The final PR #3 review found no unresolved critical findings. All 76 tests and
the standalone synthetic rehearsal passed from a clean checkout at
`2e6b093d691be097110984eea974e7c6e7a90fb6`. Baseline/source/configuration/calibration
and production selection bytes match the merged PR #2 revision. The only final
handoff addition is this maintenance note and a README link; no Python code changed.

## Thursday, November 12, 2026 — intake gate

Retrieve the actual commissioner's Week 10 attachment from Thursday's Gmail
delivery. Gmail access is not connected in the current tool session; this note
is not evidence of a configured mail download. An operator must make the actual
attachment available privately unless an authorized connection is established.
Retain message ID, receipt time, attachment filename and checksum. Validate the
actual week, every parsed game/line, submission deadline and early-game exceptions.
Use [operator checklist](WEEK_10_CHECKLIST.md). Missing PDF/instructions means NO-GO.

## Saturday, November 14, 2026 — recording gate

Only proceed with the validated actual sheet/rules, genuine fresh captures with
receipt timestamps, frozen source/configuration checks and confirmed private
durable storage/backup. Finish both cards/ledger before all applicable locks.
Noon Eastern / 17:00 UTC is an expected main lock, not a substitute for the actual
commissioner's instructions. Respect earlier exceptions; do not backdate or fill
missing observations from later/closing odds. Incomplete/late/unverified inputs
mean NO-GO or explicitly reported coverage gaps, never manufactured evidence.

Run the existing commands in [Week 10 operations](WEEK_10_OPERATIONS.md). Record
real submissions separately; the ledger does not submit to the pool. Grade only
verified finals; pushes lose. Produce the research report with sample sizes and
pending/coverage warnings. Preserve immutable private artifacts and backups.

## Current evidence and limits

Engineering GO for the controlled process. Real Week 10 recording remains NO-GO
until the operational gates are met. There are zero fully graded independent
prospective weeks available here; no predictive superiority/profitability claim.
See [certification](GRAND_PAPPY_CERTIFICATION.md) for evidence and limitations.
Future checkpoints are not proof that future data will exist or that a run will
succeed. Any scheduled run must report NO-GO when access, storage or data is missing.

## Checkpoint scheduling status

Attempts to create the November 12 intake and November 14 recording checkpoints
were rejected because the account is already at its five-scheduled-task limit.
No existing task was disabled or changed. **Neither checkpoint is scheduled.**
Treat the dates above as operator actions unless scheduling is explicitly arranged
later. Gmail is also unconnected; do not expect an automatic attachment download.
