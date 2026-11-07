# Phase 2: exact card selection and snapshot replay

No probability values, calibration tables, tuning thresholds, ingestion settings or run.sh invocation changed.

## Exact card selection

`beerpool.build_card` now enumerates legal five-point pairs and searches compatible three-point completions with an optimistic expected-points bound. It is exact for the existing constraints, with no dependency on a solver and no candidate truncation. The return API remains `(card, thin, ranked)`.

The objectives in order are:

1. Fill five legal slots whenever possible.
2. Preserve the configured sweet-spot preference for five-point slots: maximize qualifying slots among cards of that size. Only fall back when the preferred slots cannot be completed legally.
3. Maximize `5*p1 + 5*p2 + 3*p3 + 3*p4 + 3*p5` among these legal cards. Equal scores (within 1e-12 numerical tolerance) use stable probability/input traversal order.

This preserves the sweet-spot policy as an eligibility priority, not a newly tuned expected-value penalty. A higher-EV card that violates that policy is not preferred. Game uniqueness, explicit thesis exclusions, five-point tags and five-point environment exclusions are enforced jointly.

If five slots are infeasible, return the largest feasible partial card with an eligible five-point pair and at most three ordinary picks. If no five-point pair exists, return no card. This fixes a separate old failure where ordinary candidates could slide into five-point positions. The existing report warns about incomplete cards. No candidate probability is adjusted by the optimizer.

The old greedy comment claiming optimality was false. The deterministic regression first reproduces its four-pick 9.76-point result, then verifies a five-pick 11.66-point solution. Existing optimal archived selections remain unchanged: all five game numbers, probabilities, ordering, expected points and pre-PDF report text match the committed Week 9 archive. Other constrained boards may legitimately change to improve completeness or EV. Equal-EV alternatives follow stable traversal, not a promise to reproduce every possible historical tie ordering.

Exact search is combinatorial in the worst case, but uses only five slots and bounds/prunes tails. No approximate fallback changes its optimality guarantee.

## Offline replay foundation

`backtest/snapshot_replay.py` is a new opt-in command. It does not replace run.sh, ESPN backtests, or snapshots.py, and does not fetch data or use SQLite. Example, from the repository root:

```bash
python3 backtest/snapshot_replay.py freeze --output frozen-config.json
python3 backtest/snapshot_replay.py replay \
  --board runs/2026-11-07_0948/board.json \
  --config frozen-config.json \
  --deadline 2026-11-07T12:00 \
  --snapshots data/snapshots \
  --max-age-hours 24 \
  --output replay.json
```

The freshness limit above is an explicit replay data-quality policy, not model tuning. Without it the report warns and exposes each snapshot's age. Full team names must exist as away_name/home_name or the archived `names: Away at Home` field; missing names produce coverage gaps instead of guessed matches. Board inputs must contain correctly oriented, frozen sheet lines and original submission rules; replay does not infer a sheet favorite from live/closing odds.

`freeze` copies every Config field and the full calibration table, records creation time, and hashes beerpool.py, build_board.py, vi_parse.py and the replay implementation (which also fixes the module-level constants and algorithms). Replay requires an explicit manifest and rejects source mismatches. Artifact writes are exclusive: existing manifests/results cannot silently be overwritten. Replay embeds the manifest, input-board hash and selected snapshot byte hashes. Reusing the same files gives deterministic output. Neither the freeze nor replay command fits anything.

For one submission decision, replay:

- Normalizes naive board/decision times as Eastern; snapshot timestamps require explicit zones.
- Uses the earlier of the supplied submission time, explicit/default game lock, and kickoff. Already-locked games are explicitly excluded. Run separate earlier submissions for early games; this command does not fabricate a full multi-decision historical week.
- Selects matching snapshots by payload timestamp, never filename order, strictly **before** cutoff (equality is excluded). If received_utc exists it also must precede cutoff; availability is the later of capture/receipt.
- Uses the most recent eligible matching event snapshot and existing market aggregation/pricing. Does not combine markets across captures or backfill missing markets. Older matching captures are allowed only before cutoff and within the requested age policy.
- Removes all embedded board market odds, manual notes and MEGA instructions. No future or closing price fallback exists. Notes can only be supported later with independently timestamped provenance.
- Reports per-game cutoff/status, selected snapshot/age/receipt verification, available spread/total markets, candidate counts, pricing sweep/book-conflict flags, coverage counts, malformed snapshot errors and incomplete cards.

A covered game means a matching market snapshot exists, **not** that both markets are available or a candidate survives book filtering. Inspect markets/candidate_count/sweep for that distinction. Replay produces a decision card and expected points; it does not grade results or claim profitability.

## Tests and available-data validation

- Existing 22 engine tests preserved.
- Seven optimizer tests: four-pick regression, infeasible/no-eligible boards, deterministic ties, duplicate games, shared thesis/environment and eligibility constraints, sweet-spot fallback, 60 seeded small boards compared with an independent exhaustive oracle, and exact archived report preservation.
- Ten replay tests: strict before/equal/after filtering, UTC/Eastern conversion, payload-vs-filename order, earlier game locks, receipt filtering, missing/future-only observations, explicit age policy, malformed/naive snapshot handling, missing names, detached frozen configuration/source rejection and deterministic nonmutating replay.
- Total: 39 tests via `python3 -m unittest discover -v`.

## Remaining evidence limits

Only one archived card and four same-morning snapshots are committed. Legacy snapshots record capture start, not network receipt; the report flags them as unverified at receipt. They cannot prove information was received before a cutoff. The currently frozen calibration uses all historical seasons, so retroactive scenarios are explicitly flagged and are not independent out-of-sample results. There are no original private historical workbooks/results in this checkout. Name matching remains the existing ingestion heuristic; snapshot records lack stable event IDs and event dates, so repeated matchups/stale snapshots require particular care and a strict age policy. No multi-submission allocation, retrospective manual notes, result grading, fee/payout simulation or predictive-performance tuning is added.

Available-data CLI smoke test (24-hour age policy, Nov 7 noon ET): 78 input games,
65 matching pre-deadline markets, 13 games explicitly locked before submission;
no snapshot parse errors. The replay card uses earlier captured prices and omits
manual notes, so it is not expected to match the later 09:48 live archive.
A 250-candidate unconstrained optimizer smoke test returned five picks in about
4.9 seconds in this environment (not a worst-case performance guarantee).
`git diff --check` passed.
