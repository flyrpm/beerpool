# Ronnie Mooch v2 — Phase 1 architecture and evidence audit

Audited 2026-11-07. Repository: flyrpm/beerpool. Baseline commit: `40b118d601e8e86bffc92385446d533ac3360792`.
Scope: all 27 tracked files, including all Python/shell code, documentation, JSON configuration/team directory, board text, archived run and four compressed snapshots. No AGENTS.md was present. This document is the only tracked change; no production behavior, calibration, notes, or weekly workflow was changed.

## Assessment

A stale sheet versus a later, better-informed market is a plausible source of pool advantage. The repository does **not yet establish a genuine, repeatable pre-deadline advantage or monetary profitability**. Its retrospective performance uses closing odds, its held-out season has informed rule selection, and the underlying private historical inputs are unavailable in this checkout. This is insufficient evidence, not evidence that the strategy has no edge.

The documented 57–60% forward expectation is an unvalidated estimate. Reported historical points and win rates in README.md and LEARNINGS.md were not independently reproduced. Pool points, sportsbook return, and pool payout probability are distinct objectives. The engine optimizes a heuristic for expected pool points; it does not model entry fees, payouts, opponent behavior, or dollar returns.

## 1. Current data flow

### Weekly production

1. `run.sh:8–23` selects an explicit PDF or newest BP*.pdf in Downloads, and explicit notes or lexically latest notes JSON. It changes into the repo and writes the working board.json, then invokes beerpool.py with PDF verification and a run archive. NOW changes eligibility checks, **not** the time of the fetched market.
2. `build_board.py:51–71,225–276` runs pdftotext -layout, regex-parses sheet game numbers, teams, league sections, kickoff times, favorite, absolute spread and total. The first Saturday determines the noon ET default lock. Missing rows are silently skipped unless zero games parse.
3. `build_board.py:102–129,231–236` fetches NFL/CFB VegasInsider pages and ESPN college scoreboards; raw responses are overwritten in cache/. Offline mode reuses them. `vi_parse.py:36–51` extracts spread/total/moneyline rows using HTML regexes, positional cells and hard-coded sportsbook names.
4. `build_board.py:132–212` pairs consecutive odd/even rotations, matches both team names, uses seven book columns (excludes Kalshi/consensus), and takes a median signed home spread / total. An even-count median between actual lines becomes the upper middle observed line. At that line, average implied probabilities are converted back into American odds. Missing paired prices silently default to -110/-110. Moneylines are independently median-aggregated by side for spreads <=3.5; these need not come from identical available books. Open column values support movement flags.
5. Team identity in this path is still custom normalization/aliases, abbreviation prefixes, and a market-favorite fallback (`build_board.py:74–99,216–257`). The ESPN-ID directory in teams.py is **not integrated**, despite its introductory docstring claiming otherwise. Backtest matching is separate again.
6. Weekly notes are attached by game number and side; board contains week, default_lock, mega, as_of, games and embedded notes. `as_of` is a naive host-local timestamp generated after ingestion, not a timezone-qualified quote timestamp.
7. `beerpool.py:367–485` removes locked games (earlier kickoff or default noon, explicit override first), fits market distributions, prices four possible sides at the frozen sheet with pushes losing, calibrates, applies notes and filters. Book range trims one observation from each end when >=5 books; spread range >1 or total range >1.5 removes that market's candidates. Dallas team picks are excluded; totals involving Dallas remain possible.
8. `beerpool.py:492–541` greedily selects two five-point picks, first favoring spreads with 1.5–3 points of number value, then falling back; next selects three three-point picks. Constraints: one per game, no repeated explicit thesis, different explicit environments for five-pointers (otherwise game-specific default), eligibility tags. Missing thesis/env metadata provides little actual cross-game diversification.
9. `beerpool.py:584–682` emits sweep, candidates, card, expected points, optional MEGA submission and heuristic PDF check; saves board.json/card.txt under a minute-resolution run directory. The PDF check matches a game number and numeric line anywhere on the row, not a complete semantic assertion of team, sign, market and total. It warns rather than blocking output.

### Historical evaluation

`backtest/extract_boards.py` reads private Excel workbooks via openpyxl, handles three layouts, hard-codes seasons by layout (2025/2026), deduplicates season/week/game and marks draft sheets. It retains dates but drops kickoff times. `fetch_results.py` excludes drafts, searches both leagues within date +/-1 day, accepts the first matching team pair in either orientation, and caches ESPN scoreboards/core odds/summary responses. Completed games receive scores, event IDs and purported closing/opening prices. Provider preference is DraftKings then ESPN BET, with other non-live providers also possible; pickcenter is a fallback. Quote availability timestamps are not preserved.

`run_backtest.py:47–100` infers sheet favorite orientation and creates minimal boards from the close. It requires both closing spread and total even to retain a spread opportunity. Boards omit kickoff/lock, notes, environments, thesis and book dispersion. `candidates_by_week` calls production pricing with `now=None`; eligibility never runs. `grade` uses strict inequalities, correctly making pushes losses. It fits shrink/calibration on the selected training season, evaluates variants and aggregates pool-point comparisons. `replay_week.py` loads today's production calibration even for past weeks.

## 2. Data inventory and SQLite

| Data | Source and storage | Present / limitation |
|---|---|---|
| Sheet PDF | Commissioner, external; *.pdf ignored | Absent; one extracted board text is committed |
| Historical sheets/standings | Private Excel workbooks, openpyxl | Absent; extraction/results cache also absent |
| Historical results and open/close | ESPN APIs, backtest/cache/espn and results.json | Ignored, absent; reported 1,908 games cannot be independently checked |
| Live market | VegasInsider seven-book consensus, cache/ | Raw cached HTML absent; aggregated market present in one archived board |
| NFL margin research | nflverse games.csv, data/hist/nfl_games.csv | Ignored, absent; model research not rerun |
| Calibration | models/calibration.json | Present; train_season=0, prior=40, no dataset hash/cutoff/fit timestamp |
| Identity | models/teams.json from ESPN | Present; standalone resolver, no current production/backtest imports |
| Notes / run | notes/2026-wk09.json; runs/2026-11-07_0948 | One notes file and one board/card archive, 78 games |
| Snapshots | Parsed VegasInsider gzip JSON | Four files, NFL and CFB at 14:15:57 and 14:19:07 UTC on Nov 7 (09:15/09:19 EST) |

SQLite is used **only** in snapshots.py's build_db: it deletes/rebuilds derived data/odds.db, flattening every saved nonempty cell into `odds(taken_utc, league, market, rot, team, book, line, ou, price)` with time and team indexes. This includes Open, Kalshi and Consensus, not just the production seven. There is no stable event ID, kickoff, fetch completion, uniqueness constraint or data-version linkage. No scores, predictions, picks, bankroll or payouts live there. Production, backtest and market_at do not query SQLite; market_at reads gzip files directly. It selects the last eligible file in sorted path order per league, with no freshness or event-level validity check. This works for the current UTC filenames, but is not a complete point-in-time replay system.

The README claims a cloud snapshot job, but no cloud scheduler definition or GitHub workflow is committed. Actual ongoing execution cannot be verified. schedule_mac.sh implements a different fallback schedule using Mac-local time assumed Eastern. Neither scheduler was installed or changed.

## 3. Probability and adjustment logic

- Base distributions: discrete normal density times hand-set key-number weights. Margin support -90..90; total 0..140. NFL SDs 13.5/13; CFB 16.5/16. Means/distributions are cached to 0.01 point (`beerpool.py:39–148`). These are modeling assumptions, not fitted per-game uncertainty.
- Market fit: proportionally de-vig two American prices, then bisect mean to match conditional cover probability excluding market pushes. With moneylines, average spread-implied and ML-implied means equally. Final sheet probabilities are unconditional strict win probabilities (`:155–211,412–475`). This correctly distinguishes sportsbook refunds from pool push losses before later calibration.
- Config.legacy(): no shrink, no calibration/sweet-spot, big-move five-point cap. Default Config(): total shrink 0.5, spread 1, big moves warn, sweet-spot on. Production additionally loads models/calibration.json if present; absence silently changes the model to shrink mode (`:226–286`). Config is frozen but its nested calibration dictionary remains mutable; important settings also remain module-level constants/PMFs, so the docstring's claim that every tunable is isolated is too broad.
- Without a calibration table, p = 0.5 + k*(p_raw-0.5). Fitting searches k=0..1.5 in 0.1 steps by candidate-level Brier score.
- Calibration bins are type (spread/total) x number edge: <=0, 0.5, 1–1.5, 2–3, 3.5+. Fitted rate = (wins + 40*prior)/(n+40); prior is mean raw p except huge edges use fitted 2–3 rate. At runtime p = clamp(rate + 0.5*(raw_p-mean_p),0.25,0.75). Shrink settings are bypassed if calibration is supplied. Leagues, favorites/dogs and key-number crossings share cells.
- Committed cells total 3,644 spread candidate labels and 3,668 total labels. These are **not independent games**, because multiple sides share outcomes. Huge-edge cells have only 39 spreads and 20 totals. Their rates depend materially on the prior.
- Notes adjust p afterward by at most +/-0.02, and add/clear flags, thesis/env and explanations. There is no dated evidence record or measured incremental benefit for these nudges. Current Michigan +0.015, NMSU -0.01 and Wisconsin -0.015 alter ranking. Current Michigan QB uncertainty is narrative only; it does not automatically add qb_uncertain.
- A >=3-point open-to-current move adds big_move; >=2 against the candidate adds steam_against. Production big_move alone warns; steam_against, qb_uncertain, starter_uncertain, model_only and optional huge_edge block five-point eligibility. clear_tags can override automatic blocks. Optional huge-edge cap is off in production.
- Expected card points sum 5p/3p (linearity does not require independence); probability reliability is essential. MEGA incremental EV =10p-5 relative to a normal five-pointer, requires manual request on a first-two pick. It is pool-point EV, not financial return. Reported expected points exclude activated MEGA's incremental EV.

## 4. Findings ranked by impact

### Critical — Closing-market look-ahead and missing deadline universe

Evidence: run_backtest.py:70–100,170–175; extract_boards.py's date-only rows. Sunday/Monday closing odds include information unavailable Saturday noon. Historical boards also admit already-completed early-week games to a fresh weekly selection; no explicit earlier submissions are modeled. Dropping missing matches/odds may change which weeks or games appear. The retrospective gain cannot be used as a realizable weekly edge estimate. Calling close-based performance an upper bound is a useful warning, **not a mathematically guaranteed bound** on actual returns.

Next evidence needed: dated original sheet and earliest permissible submission records; event-specific cutoff; latest sufficiently fresh complete quote received strictly before cutoff; no later-price fallback; logged exclusions and coverage denominators. For early games model the actual earlier pick decision or mark unavailable, rather than selecting after results exist.

### High — Holdout reuse and retrospective calibration contamination

Evidence: calibration _meta train_season=0; replay_week.py:47; LEARNINGS.md explicitly says five-point thresholds came from both seasons. Fitting on all past completed results is acceptable for future deployment, but applying that table to the same weeks is in-sample. The default 2025-trained calibration run is distinct from this artifact; its 2026 test is still conditioned on observed 2026 results during rule design. `--train 0` can still label 2026 “TEST (out of sample)” in run_backtest.py:310, despite including it in training. No guard against identical train/test seasons or future training seasons.

Next: freeze rules and dated artifacts; rolling-origin outer evaluation with tuning only inside prior data; untouched prospective weeks; explicit in-sample labels for all-season fits.

### High — Historical measurement cannot currently be reproduced

Evidence: no workbooks, results.json, ESPN caches or nflverse CSV in checkout. README/LEARNINGS lack a versioned result manifest and disagree on historical scope (README describes prior Weeks 10–21, LEARNINGS says full 2025; verify from private inputs). Model metadata lacks data fingerprint and exact cutoff. One run archive stores board and report but not exact code/config/table hashes, full settings, PDF, raw feeds or separate submission record. Mutable calibration can change a replay. Minute-resolution archives can overwrite runs. Archived as_of is 14:48 without a zone while card run time is 09:48 ET: consistent with UTC ingestion, but ambiguous in schema.

Next: private immutable audit manifest and checksums, exact code/config/model versions, raw source references, timezone-qualified ingestion/quote times, and immutable submission times. Keep private pool data out of public Git.

### High — Identity/favorite inference can fabricate value

Evidence: build_board.py:247–257 falls back to current market favorite to assign the sheet abbreviation; run_backtest.py:64–66 falls back to closing spread sign when favorite resolution is ambiguous. A true favorite flip can therefore be misread or suppressed; historical inference additionally depends on future information. Shared ESPN-ID resolver is unused. Historical matching accepts first eligible pair near a date without a complete ambiguity ledger.

Next: audit all fallback-resolved rows, enforce stable team/event identities and orientation, quarantine ambiguity; require equal-or-better match coverage before integration. Do not silently infer sheet favorite from the market being tested.

### Medium — Backtest does not represent the full live system

Historical cards lack book-disagreement filtering, manual notes, thesis/env constraints and actual pre-deadline medians. Single-book closes differ from the live seven-book estimator. Results therefore do not validate the complete weekly workflow or the notes layer. Requiring both spread and total selectively excludes otherwise usable spread opportunities. Missing prices default to even juice without a report.

Next: separate market-only, market+calibration, card-rule and notes ablations on identical eligible universes; report unmatched, missing odds, defaults and exclusions by week/league.

### Medium — Greedy optimization claim is false with interacting constraints

Evidence: beerpool.py:492–538. Greedy is not generally optimal with game and thesis exclusions. A synthetic probe produces a four-pick card at EV 9.76 while a legal five-pick alternative has EV 11.66: game1/A .65 thesis X; game2/B .64 thesis X; game1/C .63 no thesis; game3/D .60; game4/E .59; game5/F .58. Greedy takes A,D,E,F; legal B,C,D,E,F fills all slots. All candidates otherwise five-eligible. This is a demonstrated counterexample, not evidence that the archived real card is suboptimal.

Next: use an independent exhaustive optimizer as an audit comparator before proposing any behavior change. Also, if fewer than two five-eligible picks exist, build_card can append ordinary picks and report scores them as first-slot five-pointers; validate slot legality explicitly. Thin-board checks only the best candidate, not the selected card's lower slots.

### Medium — Calibration and statistical certainty exceed evidence

Binning gaps send positive off-grid edges such as 0.25, 0.75, 1.75 and 3.25 into <=0. Current quoted half-point data generally avoid this, but schema does not enforce it. Independently calibrated mutually exclusive sides need not preserve push mass or sum <=1. Normalized prediction probabilities are not guaranteed by calibration. Candidate counts and naive printed +/-1.96*sqrt(.25/n) intervals ignore within-game, weekly and selection dependence. No cluster-aware confidence intervals for selected-card gains, no predeclared superiority threshold and no prospective sample-size plan exist.

Next: validate allowed line increments and probability coherence in an offline audit; evaluate Brier/log loss/reliability by league, type, edge and selected slot; estimate paired weekly gains with appropriate dependence-aware intervals. Specify minimum meaningful gain and required precision before claiming success.

### Medium — Snapshot availability and freshness are incomplete

Four snapshots on one day are not a longitudinal test. take() timestamps before sequential network fetches; receipt can be later, even beyond deadline. Per-book quote age, event ID and kickoff are absent; same-minute captures overwrite. market_at enforces captured timestamp <=requested time but no maximum age or event-specific lock, and selects whole league snapshots, not a validated quote per event. Late or partial captures may be accepted without clear coverage accounting. Scheduler operation is unverified.

Next: record capture start/end/receipt, explicit success and event IDs; reject after-deadline receipt and stale/missing observations in a new offline evaluator. Keep current production untouched until validated.

## 5. Complexity not yet supported by sufficient evidence

| Component | Existing evidence | Remaining gap |
|---|---|---|
| Key-number distributions and SDs | NFL empirical comparison reported; standard push-aware rationale | Many hand-set weights; no CFB-specific external validation or uncertainty analysis |
| Empirical kernel model | margin_model.evaluate trains 2006–2021, tests available 2022–2029 rows | NFL only; synthetic +/-3 sheet offsets, correlated labels per game, no selection-policy test; parametric comparison uses direct mean s, not production de-vig/ML calibration |
| NFL total SD=13 | Reported better than 10.5 on the same test | Repeated inspection/model choice consumes that holdout; tiny metric differences need paired uncertainty |
| Calibration | Training-only code path exists, 40-pick pooling | Prior=40, within-cell slope=.5, huge-edge prior choice and bucket boundaries lack nested/forward validation; small tails |
| Five-point sweet spot | Retrospective reported improvement | Rule selected using both seasons; independent future benefit unknown |
| ML mean blending | Directionality unit test | Equal weighting and <=3.5 cutoff have no demonstrated incremental forward gain |
| Book trim/move thresholds | Practical heuristics, historical movement comparisons | Single-book historical test cannot validate multi-book filter; thresholds/move-cause tags need prospective evaluation |
| Manual nudges/tag clearing | Narrative rationale and clamp tests | No frozen source timestamps, incremental scoring, blinded evaluation or adjustment calibration |
| Thesis/environment bans | Intended diversification | Sparse metadata; no covariance/payout evidence; expected points and tournament utility are different objectives |
| Huge-edge cap | Disabled comparative option | Do not promote another rule based on thin reused tail results |

margin_model.py has no current production import, despite its lookup comment suggesting otherwise. Symmetric margin training rows and multiple test offsets improve construction/coverage but do not create independent games. Its test horizon is open to new data (range 2022..2029); the cached CSV's actual contents determine the sample. Data version must be pinned before comparing runs.

## Verification performed

- Existing `python3 -m unittest test_beerpool`: **22 passed**. Mostly legacy rules, arithmetic and helper checks; passing is not predictive validation. No ingestion/backtest/time-of-information integration tests exist in the suite.
- Rebuilt report from archived board with production config at 2026-11-07 09:48 ET: **exact match before the PDF-check section**, including submission and expected points. Original PDF absent, so PDF verification was not rerun.
- Parsed all four gzip snapshots: CFB 378 rows and NFL 90 rows per capture.
- Built SQLite in a temporary directory: **9,144 cells**, CFB 7,352 and NFL 1,792. No production DB was changed.
- market_at before Nov 6 noon: no snapshots; before Nov 7 noon: both leagues select 14:19:07 UTC.
- Demonstrated off-grid bucket fallback and greedy constraint counterexample above without modifying engine code.
- Read complete team directory/configuration, notes, board and run artifacts; inspected repository history. Historical claimed performance, cloud job execution, current live market and monetary returns were not independently tested. No new external feeds fetched, calibration fit, scheduled job run, or picks submitted.

## Incremental next steps (proposals only)

1. Obtain the private workbooks/results cache and original submission/decision records through an appropriate private workspace. Produce a coverage/reconciliation manifest before recomputing any result. Do not post private pool data publicly.
2. Add a separate offline audit command that enforces event cutoff and quote receipt times, uses existing pricing functions and explicit immutable Config objects, and never changes run.sh or production defaults. Label legacy close-based runs diagnostic only.
3. Freeze a baseline and prospective evaluation protocol; record every eligible candidate, selected card, notes known by cutoff, model hashes and submission. Separate decisions for early games. Do not backfill unknown facts.
4. Compare simple market-at-sheet pricing, existing production calibration and individual rule/notes ablations on the same universe using chronological outer folds. Keep the five-point rule's already-inspected seasons as development data. Include a legal-card optimizer comparator and correct slot checks.
5. Report paired weekly point gains and uncertainty, proper probability scores and calibration, stale/missing coverage, stability across NFL/CFB and seasons. For profitability, separately obtain actual fees/payout rules and model season outcomes and opponent dependence. No sportsbook ROI claim follows from unavailable sheet prices.

Phase 1 exit: architecture and blockers documented; current code and weekly behavior preserved. A predictive-advantage claim remains **unproven pending deadline-correct, reproducible, independent evaluation**.
