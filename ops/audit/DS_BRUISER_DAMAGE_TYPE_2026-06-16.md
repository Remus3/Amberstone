# DS bruiser scorer vs enemy damage type - investigation verdict

2026-06-16. Spawned from the cycle-56 live-support thread (Jarvan IV ARAM). Read-only analysis; NO engine change made.

## Question

Should the DS bruiser archetype scorer (`agents/daemon_slayer/hybrid.py`, `/rank-bruiser`) respond to the enemy AD/AP damage-type split? Observed earlier: the top-5 item ranking was byte-identical at `enemy_ap_share` 0.5 vs 0.9 (Jarvan IV ARAM lvl 12, items 6631/3111/1029/6610, target_armor=122/target_mr=83), even though the tank/EHP scorer responds strongly.

## Verdict: NOT a bug. The bruiser scorer IS damage-type-aware.

The "byte-identical top-5" was real but MISLEADING. Pulling the full ranking (top 60) at both shares shows the damage-type signal works correctly - MR items rise and armor items fall as AP share rises:

| item (resist type) | rank @ ap0.5 | rank @ ap0.9 |
|---|---|---|
| Wit's End (MR)        | #14 (+ehp 604)  | #9  (+ehp 1087) |
| Maw of Malmortius (MR)| #31 (+ehp 979)  | #15 (+ehp 1763) |
| Kaenic Rookern (MR)   | #52 (+ehp 1997) | #29 (+ehp 2948) |
| Mercurial Scimitar(MR)| #45             | #32             |
| Spirit Visage (MR)    | (n/a)           | #47 (entered)   |
| Force of Nature (MR)  | (n/a)           | #44 (entered)   |
| Randuin's Omen (armor)| #58 (+ehp 1805) | out (fell)      |
| Dead Man's Plate(armor)| #29 (+ehp 1501)| #48 (fell 19)   |
| Sterak's Gage (HP)    | #18             | #19 (stable, HP not resist-typed) |

`enemy_ap_share` correctly flows comp -> `compute_ehp` -> per-item `delta_ehp` -> `hybrid_delta_pct`. The ordering is right.

## Why the visible top-5 does not move

The hybrid sort key is `hybrid_delta_pct = alpha*(delta_dps/baseline_dps) + beta*(delta_ehp/baseline_ehp)` (`_hybrid_delta_pct`). Jarvan weights are alpha=0.55, beta=0.45 (NOT tiny). The issue is a NORMALIZER ASYMMETRY in practice:

- `baseline_dps` ~69 (weighted/sustained DPS) is SMALL, so a +100 DPS item = +145% DPS.
- `baseline_ehp` ~4900 is LARGE, so even a +1800 EHP MR item = only +37% EHP.

So the whole EHP tier (best MR item Wit's End h% ~39) sits below the pure-DPS tier (Runaan's h% ~80, Kraken h% ~45) regardless of beta or ap_share. The damage-type signal reshuffles positions ~9-60 correctly; it just cannot lift an MR item into the DPS-dominated top-8.

## Recommendation: do NOT change weights now

1. There is no defect to fix - the engine is damage-type-correct.
2. Whether the bruiser blend SHOULD surface a resist item into the visible top-5 vs a hard-AP comp is a CALIBRATION judgment, not an obvious correctness fix. Bruisers are intentionally damage-leaning; forcing MR into the top-5 risks over-tanking bruisers globally.
3. If pursued, the principled path is per-champion calibration against rewind_history.db WIN outcomes (exactly the "Phase 2.5 per-champion calibration from rewind logs" the `hybrid.py` docstring already defers), NOT an eyeballed global beta bump. Validate per-champion (Jarvan is one of 20 overrides), bump ENGINE_VERSION, run the dual suite + Share mirror sync.
4. Immediate user-facing lever for "frontline champ vs AP-CC comp" already exists and IS strongly damage-responsive: the TANK archetype pick (`/rank-tank` puts Kaenic Rookern / Force of Nature / Spirit Visage top-5 at ap0.9). Steer a tank-leaning bruiser to the tank archetype via the ds-knobs archetype pick.

## Flagged sibling (separate, out of scope here)

`/rank-bruiser` ranks Runaan's Hurricane (#2), Kraken Slayer, Stormrazor, Yun Tal for MELEE Jarvan - crit/AS marksman items whose value (esp. Runaan's bolts) does not apply to a melee auto. Worth a separate look at the bruiser candidate pool / DPS crediting for melee champs; unrelated to damage-type responsiveness.
