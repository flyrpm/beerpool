# Grand Pappy Certification — Heady Topper Technologies

Assessment date: November 7, 2026. Repository: flyrpm/beerpool.

## Decision

**GO — engineering foundation for controlled forward collection.** PR #2 was
reviewed from a clean checkout and merged after its full matrix passed. The
synthetic end-to-end rehearsal passes. Source/model/calibration/selection and
`ronnie-v1` remain unchanged. The research dashboard is an additive reporting
module, not a model revision or new application.

**NO-GO — real Week 10 recording today.** The actual commissioner PDF, actual
submission instructions/early exceptions, genuine Week 10 captures and durable
private backup destination remain unverified. They are operational gates, not
facts this certification can infer. Do not invent a slate, backdate records or
mark a retrospective/synthetic run prospective.

**NOT VALIDATED — predictive superiority or profitability.** There are zero
fully graded independent prospective weeks available in this workspace. Test
success establishes software behavior, not an edge. No financial return,
statistical significance or payout advantage is claimed.

## Final PR #2 review and merge

PR: https://github.com/flyrpm/beerpool/pull/2

Reviewed head: `914b43bb5f3e3855401685387c127562a2bbb015`.
Merge: `6fade5296a1467f4e1fd69198c738f0919f6e65f`.
No conflicts or unresolved review threads; no additional merge blocker found.

Evidence:

- Clean clone at the reviewed commit: 70 tests passed, working tree unchanged.
- Frozen source hashes compared with exact Git objects at
  `6411fe24f9f1dd4cd23398d12f9daa0e6b311816`.
- Raw calibration file hash and parsed calibration verified against that Git
  revision and the manifest's embedded configuration.
- PR matrix: https://github.com/flyrpm/beerpool/actions/runs/42395204967
- Merge-to-main matrix: https://github.com/flyrpm/beerpool/actions/runs/42395766769
- Both matrices passed Python 3.10, 3.11, 3.12 and 3.13. Original archived-card,
  optimizer, provenance, deadline, scoring and isolation regressions remain green.

## Architecture and preserved safeguards

The project remains Python standard library, filesystem snapshots, derived SQLite
odds cache and Git/GitHub. No new database, paid service, model, dashboard server
or Python package was introduced. CI supplies the existing `pdftotext` ingestion
dependency when absent.

The baseline file is byte-for-byte unchanged:

- ID: `ronnie-v1-2026-11-07`.
- Payload checksum: `34c0e939c58c25ef0d15c9434bc164b3e632b218e36e909316b8d7939806a1f3`.
- Pinned source revision: `6411fe24f9f1dd4cd23398d12f9daa0e6b311816`.

Recording still enforces strict pre-decision snapshot capture/receipt times,
24-hour freshness, matching source/config hashes and effective earlier game
locks through atomic exclusive ledger publication. No live/closing-odds fallback
exists. Both variants share captured inputs and retain separate configurations.
Scoring remains two five-point and three three-point slots; pushes lose. Missing
markets and incomplete cards are visible. Missing, canceled and nonfinal results
remain ungraded; result identities/scores and operator evidence are validated.
Historical and synthetic records are excluded from paired prospective totals.

The frozen `backtest/evaluation.py` reporter is deliberately unchanged. New
`backtest/research_report.py` composes it and displays rates/calibration. It
includes every recorded season week, even if `--weeks` names only expected
additional weeks, so the research command cannot silently omit recorded weeks
from its cumulative display.

## Synthetic operational rehearsal

Run:

```bash
python3 backtest/certify.py
python3 -m unittest discover -v
```

The rehearsal requires `pdftotext`. Fixtures live only in a temporary directory
named `SYNTHETIC-week10-*` and are deleted on completion. It uses a test-only
November 14/15 clock and mocked network transport. Actual PDF extraction, sheet
regex ingestion, VegasInsider HTML parsing, odds aggregation, snapshot storage,
source checks, pricing, optimization, ledger serialization, grading and reporting
execute normally. This verifies software, not live provider availability.

Checks:

1. Generate and extract an explicitly synthetic PDF with seven fabricated games.
2. Parse synthetic sportsbook HTML and save two timestamped capture files.
3. Deliberately poison embedded board odds; predictions still use captured -4.5 lines.
4. Generate five frozen selections per variant using the real baseline.
5. Exercise prospective save-time gates with the synthetic clock, then relabel at
   the write boundary so no saved artifact is ever classified as prospective.
6. Verify exclusive duplicate-write rejection, deadline equality rejection and
   rejection of captures not received before recording start.
7. Exclude one earlier locked game; report one game with no matching market.
8. Ingest a synthetic source-cited final-results JSON, grade wins/losses and an
   integer-line push, and independently check the weighted Beer Points.
9. Produce pending and final JSON/Markdown reports with missing Week 11 coverage.
10. Confirm the synthetic ledger contributes **zero** prospective weeks or points
    to cumulative evidence; confirm the baseline bytes remain unchanged.

The summary says `SYNTHETIC REHEARSAL — NOT PROSPECTIVE EVIDENCE`. No raw synthetic
inputs or records are committed as real observations. No real Week 10 predictions
or scores were created. Clean-checkout execution and the full 76-test matrix are
required for the certification additions as well as the original PR #2 checks.

## Research CLI report

The operator checklist contains the complete invocation. The new report includes:

- Weekly Ronnie and benchmark selections, frozen expected Beer Points, realized
  points so far, pending counts and finalized-week point differential.
- Paired cumulative realized/expected points and differential.
- Predicted versus observed win rates on the **same graded selected picks**,
  Brier score and fixed descriptive 0.1-wide probability-bin summaries.
- Prominent graded `n`, pending count, bin counts, coverage and warnings.
- Number of fully graded paired prospective weeks, excluding different-baseline,
  historical, synthetic and incomplete weeks.

Rates and bins are descriptive, not independent-trial inference. Pending outcomes
are excluded from both sides of a rate comparison; empty samples show N/A. No
threshold, probability or production selection is tuned from this output.

## Private data and Week 10 readiness

`git check-ignore` confirms default `data/predictions/`, `data/grades/` and
`data/evaluation/` artifacts stay out of Git. No private prediction/result export
is tracked. This protects known staging paths, not arbitrary operator-selected
paths or deliberate `git add -f`.

Confirmed: frozen configuration/benchmark/source integrity, Python/pdftotext in
this environment, repeatable record/grade/report commands and ignored staging.

Pending: actual Week 10 commissioner PDF; actual deadline and early exceptions;
fresh genuine Week 10 captures; named durable private storage and verified backup.
Expected Nov 14 noon Eastern / 17:00 UTC remains a planning assumption until the
commissioner's actual instructions are checked. No runtime scheduling or actual
pool submission has been installed or performed.

Execute [Week 10 checklist](WEEK_10_CHECKLIST.md) and
[operating procedure](WEEK_10_OPERATIONS.md). Any missing gate means no-go for real
recording. If a record/card is incomplete, retain and report the gap rather than
quietly replacing it after lock.

## Limitations and unresolved risks

No unresolved merge-blocking software defect was found in PR #2. Remaining risks:

- Local clocks/checksums are not independently trusted timestamp/submission
  attestation or tamper-proof storage. Durable backup/restore is still an operator gate.
- Team matching remains heuristic; verify PDF orientation. Stable provider event
  IDs, automated verified score exports and rescheduling policy are future work.
- One evaluation decision per week; no multi-submission early-game allocation.
- Existing calibration incorporates inspected historical seasons; only future
  independent observations can test generalization.
- Snapshot/live provider layout and availability are not certified by mocked
  transport. Inspect real capture coverage before lock.
- Atomic publication requires same-filesystem hard-link support. Clean-checkout
  reproduction requires full Git history for pinned-source verification.
- No uncertainty model, payout simulation, bankroll/ROI or significance test is
  implied by a descriptive point differential.
