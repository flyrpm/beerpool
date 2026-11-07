# Week 10 operator checklist — November 14, 2026

Status as of November 7: engineering checks pass; **NO-GO for real recording until
all required inputs and storage are confirmed**. The expected noon Eastern lock
is a planning assumption, not verified commissioner instructions.

Before lock:

- [ ] Obtain the actual commissioner Week 10 PDF; retain original privately.
- [ ] Verify the actual submission deadline and early-game exceptions. Expected
      main lock: Nov 14 noon Eastern / 17:00 UTC. Do not infer confirmation from a filename.
- [ ] Confirm a private durable storage destination AND backup/restore procedure.
      Ignored local staging directories are not a durable backup.
- [x] Use `evaluation/baselines/ronnie-v1.json`, ID `ronnie-v1-2026-11-07`;
      checksum `34c0e939c58c25ef0d15c9434bc164b3e632b218e36e909316b8d7939806a1f3`.
- [x] Source revision `6411fe24f9f1dd4cd23398d12f9daa0e6b311816` and both configurations
      verified. Do not refit, change settings or recreate this baseline.
- [ ] Recheck environment clock/timezone, Python >=3.10 and `pdftotext` availability
      on the machine actually performing the recording.
- [ ] Parse actual PDF and compare every game number, team/favorite, kickoff,
      sheet spread/total and default lock with the source document.
- [ ] Capture genuine sportsbook pages shortly before recording. Selected captures
      need receipt timestamps, must predate recording start, and must be <=24h old.
- [ ] Run the baseline record command with the actual confirmed deadline. Finish
      before every applicable game lock; do not wait until the last minute.
- [ ] Inspect both five-pick cards, expected points, all-candidate probabilities,
      source/snapshot hashes, timestamps, coverage and warnings. Record gaps honestly.
- [ ] Retain immutable ledger and snapshots in private storage and verify backup.
- [ ] Submit picks through the authorized pool process and retain the actual receipt.
      The ledger does not submit picks or prove an external submission.

After games:

- [ ] Verify final scores against source URLs/event IDs; retain original evidence
      and real completion/verification timestamps. Missing/nonfinal results stay pending.
- [ ] Generate new-version JSON/Markdown research reports with sample sizes.
      Pushes lose; never edit a prior prediction record.
- [ ] Compare paired cumulative points only for fully graded prospective weeks on
      this baseline. Do not tune from those outcomes or claim significance from a small sample.

Use [Week 10 operations](WEEK_10_OPERATIONS.md) for capture and recording commands.
For research reporting (paths are private ignored staging examples):

```bash
python3 backtest/research_report.py \
  --baseline evaluation/baselines/ronnie-v1.json \
  --ledger data/predictions --season 2026 --weeks 10 \
  --output data/evaluation/week10-v1.json \
  --markdown data/evaluation/week10-v1.md
```

Create the private output directory first. While results are unavailable omit
`--results`; afterward add `--results /PRIVATE/PATH/verified-results.json` using
the exact export/evidence schema in the operating procedure. Use a new report
filename each time. All recorded season weeks remain visible; `--weeks` adds
expected missing-week coverage rather than filtering recorded weeks away.
