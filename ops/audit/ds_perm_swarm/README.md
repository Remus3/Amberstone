# DS Permutation Swarm - WIN-Anchor Harness (DSP1)

Foundation for the DS permutation swarm (docs/DS_PERMUTATION_SWARM_PLAN.md). Scores
Daemon Slayer top-N item rankings against real WIN outcomes so every later DSP/DSV
seam can be validated outcome-first instead of eyeballed. BUILD-only - no engine state,
no ENGINE_VERSION bump.

## What it does

For each (champion x mode x DS-comp-bucket):

1. DS top-N = the per-bucket `comp_grid` ranking from the 2026-06-16 cross-eval
   (`ops/audit/ds_cross_eval/data/<Champ>.json`).
2. WIN anchor = per-item win-rate + champion baseline win-rate, read live from
   `data/rewind_history.db` (`win_anchor.py`).
3. Alignment = `lift = mean(WR of DS-top-K items with n >= min_item_n) - baseline_wr`.
   A difference of differences (item-WR vs baseline), robust to the small per-item
   samples in rewind data - NOT a fragile cross-item equality. A softer rank
   correlation (DS goodness vs WR) is reported alongside.

Positive lift = DS favors items that empirically win for that champion.

## Modules

- `cross_eval_loader.py` - parse `<Champ>.json` into typed DS rankings + empirical block.
- `win_anchor.py` - per-(champ x mode) baseline + per-item WR from a sqlite connection.
- `perm_score.py` - the difference-of-differences scorer + `build_report` aggregator.
- `run_harness.py` - CLI: open the real db, score all 172 champs, write `report/`.

## Run

```
python ops/audit/ds_perm_swarm/run_harness.py --top-k 6 --min-item-n 5
```

Writes `report/perm_anchor_report.{json,md}` (atomic). The 1.8GB `rewind_history.db`
is gitignored, so the CLI runs on a box that has it (Legion). The hermetic tests in
`tests/test_ds_perm_swarm.py` synthesize their own sqlite + cross-eval fixtures and
never touch the real db (clean-checkout safe).

## Scope

DSP1 ships the harness + WIN anchor only. It does not change DS rankings; the
DSP2/DSP3 cluster fixes and DSP4-DSP8 seam work consume this report to target and
validate changes. No live-game flip here.
