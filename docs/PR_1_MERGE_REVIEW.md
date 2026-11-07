# PR #1 merge-readiness review

Reviewed the ledger/replay, snapshot storage, benchmark construction, result grader,
existing tests and CI workflow. Production beerpool.py, Config/calibration,
models/calibration.json, card-selection logic and run.sh are unchanged by this PR.
The archived optimal-card regression remains part of every matrix run.

## Merge-blocking findings found and resolved

1. **High: snapshot overwrite.** Minute-only paths plus gzip write mode silently
   replaced earlier captures. New paths include UTC microseconds and a random ID;
   temporary-file/fsync plus exclusive hard-link publication prevents replacement
   even for a forced clock/ID collision and keeps partial gzip files invisible.
   Regressions capture twice at the exact same microsecond with distinct contents,
   assert both survive and the first bytes are unchanged, force an ID collision,
   and simulate publication failure. Legacy snapshot filenames still work.
2. **High: mismatched provenance under concurrent file replacement.** Replay parsed
   a file and later reread it to hash, so odds could come from capture A while the
   recorded hash described B. It now decompresses and hashes one byte buffer.
   A regression replaces the file after loading and proves prediction/hash still
   describe the same original bytes. Both variants use a single shared snapshot
   read set, eliminating a second-directory-scan race. Benchmark configs and
   caller inputs are detached; isolation tests prove production settings unchanged.
3. **High: prospective completion/persistence could cross an earlier pool lock.**
   Only the CLI deadline and kickoff were checked after recording. A later CLI
   deadline could allow publication after the sheet's earlier lock. The ledger
   now freezes min(CLI deadline, explicit/default game lock, kickoff), checks
   recording completion against every predicted game's lock, and rechecks after
   serialization/fsync just before publication. If time expires while preparing
   the file, no ledger entry is published. Tests cover default-lock crossings
   during recording and persistence, including equality. Existing strict
   snapshot/receipt deadline filtering remains unchanged.

No unresolved merge blocker was found after these fixes, conditional on the full
CI matrix passing at the final pushed revision. This document does not approve
an automatic merge.

## Grading and benchmark checks

- Market-only disables calibration, shrink and optional huge-edge cap only for
  its detached Config; existing selection rules are shared. Both variants use the
  same sheet, candidate universe and frozen market bytes. No production setting
  is mutated or fitted.
- Spread grading uses side-oriented margin plus frozen sheet line; total grading
  uses strict over/under comparisons. Integer-line pushes lose. Missing/canceled
  results remain pending; wrong team/league/kickoff, duplicate finals, future
  completion timestamps and invalid scores fail closed.
- Grading never calls pricing or loads current calibration/snapshots. A regression
  makes repricing raise if attempted, then verifies all five pushes earn zero
  points. Paired weekly comparisons require two complete fully finalized cards.
- Integrity checks reject modified payloads; reports also identify the grader
  source and input results. These checks detect accidental corruption, not a
  deliberate rewrite accompanied by a recomputed checksum.

## Future enhancements (not merge blockers)

- Independent timestamp attestation, signed records, durable private backups and
  directory-level power-loss recovery; local checks/hashes do not prove external
  submission or training-data independence.
- Stable provider event IDs and automated verified result exports, with an
  explicit rescheduling/correction policy. Current exact identity matching fails
  closed and leaves missing/nonfinal results ungraded.
- Multiple early-game submissions in one week, aggregate prospective evaluation
  and dependence-aware uncertainty estimates. Current ledger supports one
  evaluation decision per week and reports descriptive metrics only.
- Snapshot/ledger publication requires a filesystem supporting same-directory
  hard links (Linux CI and normal macOS filesystems); unsupported storage fails
  explicitly, without a weaker overwrite fallback.

## Validation

61 tests cover the prior 50 plus snapshot collision/storage regressions,
provenance replacement, single-read benchmark isolation, earlier-lock enforcement,
future-at-recording observations, grading without repricing, and corrupt captures.
`python3 -m unittest discover -v` and `git diff --check` pass locally. The final
GitHub matrix is checked separately on Python 3.10, 3.11, 3.12 and 3.13.
