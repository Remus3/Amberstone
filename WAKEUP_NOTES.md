# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-26k - RM-117 chain verified, full-corpus table read, multikills SHIPPED. 6 commits.

**NOT a DS session.** No ENGINE bump, no Share mirror, nothing under `agents/daemon_slayer/`.

## Chain state - nothing failed, do not "repair" it
`timeline_ingest` CLOSED at **3005**. `build_rank_baselines` pid 17616 was still
alive at wrap (14/31 cohorts, ~170s each), started 10:25 - it PREDATES the
session, so it is not session-owned and survives `/clear`. **`RC-ReplayRosterPull`
Disabled with a non-empty `busy` list is CORRECT, not a stuck watchdog** -
`replay_chain_watch.py:93` short-circuits while an ingest holds the rate budget.
`RC-ReplayChainWatch` runs PT15M (verified `LastTaskResult=0`, NextRunTime live)
and owns re-enabling RosterPull + the miner. Verified `needs_mine()` is **False**
(`matches: 3005` vs `timelines_count() 3005`) so it will NOT re-mine in a loop.

## Full-corpus table (3005 matches, 44 remakes dropped, 2094/2094 per role)
Mined manually - the miner is local-only, no Riot calls, so it did not have to
wait on the rate budget. Written up as `REPLAY_T2_PARSE_CRITERIA.md` **4b-4**.
**Nothing promoted.** JUNGLE `plate_share` HOLDS and strengthens: 0.082 vs 0.045,
**effect 0.49** (was 0.46) - still the only survivor. `kill_participation` still
inert in all 5 roles at 2x corpus. Two new rows both die: TOP `plate_share` -0.21
NOT REPRODUCED **with the sign inverted**; `solo_deaths_per_min` carries LESS
signal than the `deaths_per_min` axis it subsets, so it is that restatement plus
noise.

## Shipped
Postgame narrative now carries CHAMPION_SPECIAL_KILL (`5a5ac3f6`, `ae1d6f19`) and
named/tiered objectives + buildings (`114f4d6c`). Three real defects found by
rendering actual matches, not by reading code: Riot emits **one row per multikill
rung** (a penta arrives as double->triple->quadra->penta and ate 2 of 5 slots); a
penta that aces emits both at the same ts and they collided in the dedup key; and
**all 4803 inhibitors scored 35 instead of 50** because the impact branch read
`tower_type`, which is NULL on inhibitor rows. Module is SHADOW-ONLY - no live
coach path flipped.

## Docs
ROADMAP.md was **already over its 80KB budget at HEAD** (82977) before this
session. Two relocation passes (`156dbe0e`, `a83360b8`) took it to **71819**; the
RM-79..RM-98 shape-backlog bullet went 16290 -> 7506. 21 CLOSED entries relocated
VERBATIM to ROADMAP_HISTORY.md, each leaving a pointer that keeps its fences AND
its measurement traps. Zero RM ids lost (diffed against HEAD).

## Owed
`rank_baselines.json` (31 cohorts) not yet on disk - **the PGR cohort-band check
is the only thing left**: `python tools/pgr_event_report.py --latest --pid 1`
should stop printing `rank_baselines.json absent`. Retention policy still blocked
on a 2nd `rofl_archive_growth.jsonl` sample (1 sample as of 12:32; mtimes CANNOT
answer it - bulk seed day). Quarantine PURGED this session (8 files, 24.7 MB).

---

# 2026-07-26j - REPLAY ANALYSIS SUBSTRATE (RM-117, LEDGER 1062). 28 commits, 112 tests.

**NOT a DS session.** No ENGINE bump, no Share mirror, nothing under `agents/daemon_slayer/`.

## The one thing to carry forward
The brief assumed frame-level replay analysis needed the Settled `.rofl` Layer-2
fence opened. **It does not, and the fence stays CLOSED.** Four measurements:
1. The v2 container has NO encryption - plain zstd, stdlib-openable. The
   roflxd/Blowfish layout everyone cites is the OLDER v1 container. The fence's
   crypto rationale is void; its CHURN rationale stands (2 builds inside 16.14).
2. Positions come from the sanctioned replay API at **~19 map units** via an
   analytic ray/ground-plane solve. `cameraRotation` is `{x:YAW, y:PITCH}`, the
   camera looks `h/tan(p)` AHEAD of its own coords, and `cameraPosition` is
   writable ONLY in `cameraMode:"fps"`.
3. **Match-V5 60 s positions carry ~2000 units of error** (replicated on 2 games;
   8 of 33 samples wrong by more than the 2750-unit decision threshold). An
   earlier claim in this same session that the signal decay was "real behaviour"
   is RETRACTED in-file - it was sampling noise.
4. Paused renders are BIT-DETERMINISTIC (0 px), so flipping one entity toggle
   makes the pixel diff that entity class. **Wave state and ward coverage both
   unblock** with no ML. Buff camps untried.

## Running unattended - DO NOT ASSUME THESE FINISHED
- `timeline_ingest` pid 7580: **1092 / 3005** timelines at hand-off.
- `build_rank_baselines` pid 17616: waiting for idle, then 31 per-division cohorts.
- **`RC-ReplayChainWatch`** (new, PT15M) re-enables `RC-ReplayRosterPull` and runs
  the miner once both finish. `RC-ReplayRosterPull` is **Disabled** until it does.
- **GAP:** nothing restarts `timeline_ingest` if it died. Check the count first;
  it is resumable and skips existing files.

## Don't-redo
No fetch-by-match-id route exists (two requested matches rotated out of the
5-wide window mid-session, permanently gone) - never plan a `.rofl` backfill.
Summoner spells are LOADOUT ONLY (no Flash/TP/Smite timings anywhere). Buff
intervals and sharing are unrecoverable. Do not re-derive `FAR_UNITS` /
`SIGNAL_DECAY` as jungler facts.

## Owed / operator-gated
**B13** - Riot's acceptable-use position on bulk replay harvesting at
108-account scale is UNMEASURED. No retention policy on a 6.78 GB corpus
growing hourly. The win/loss promotion gate is BUILT but UNRUN at scale.

---

# 2026-07-26i - RM-95b residual SHIPPED: population 3 measured down to 1

**Shipped:** ENGINE 1.256.0 -> **1.257.0**, DEFAULT-OFF `apply_wiki_form_damage`. LEDGER 1061.
Tier-2 - new engine registry + an `abilities.py` seam, so the full dual suite, the Share
mirror, the DS `:8893` bounce and a four-family build-order regen all rode.

**The headline is that two thirds of the filed item was a refutation, and the row's own
filter is why.** RM-95b B2's closing sentence left a residual: "Three hand-authored registry
entries are the proportionate fix", naming Jayce W Hyper Charge, Mel W Rebuttal and Quinn R
Skystrike. That population came from a filter over the DATA ("names a real damage label AND
carries no `attribute_kind == "damage"` block"). Re-running it against the live snapshot
AND the live EVALUATOR - the question a build engine actually answers - collapses it to 1.

**The one that is real: Quinn's ultimate contributed exactly 0.0 to her own ability lane.**
Quinn R ships as two forms. Form 1 `Skystrike` carries ZERO blocks; form 0 `Behind Enemy
Lines` carries only a movement-speed modifier - and form 0 is the one the engine SERVES,
because `get_form_index_for("Quinn")` returns `({}, 'default')`. Measured at L13 against the
sweep-standard tanky target: R `raw_damage_per_cast` **exactly 0.0** while Q read 205.0 and E
read 40.0. The movement-speed modifier is correctly credited zero, so this was a silent
absence rather than a mis-credit - which is exactly why nothing caught it.

**Authoring onto the SERVED form is the load-bearing detail.** Putting the block on form 1 -
the form actually NAMED Skystrike - produces a block the evaluator never reads; re-routing R
to form 1 instead swaps in a form whose `cooldown` and `cost` are both `None`. So it is
PREPENDED onto form 0 (damage-first, since `_select_blocks` reads `damage_blocks[0]` and
Quinn carries no block-index override), labelled `Skystrike Physical Damage`, with a guard
pinning `get_form_index_for("Quinn")` at the default so a future form-registry change goes
RED instead of silently unreading the entry. Armed on Quinn L13 SR `[3031, 3006, 6672]`:
R **0.0 -> 132.0** raw, total ability DPS **4.1864 -> 4.5815**.

**The two refutations, both pinned as tests so the population-is-3 reading cannot come back.**
Jayce W Hyper Charge already has its numbers on disk (`[70, 78, 86, 94, 102, 110] % AD`), and
the served Jayce W form is `Lightning Field` at a real 380.0 raw - Hyper Charge is the
Mercury-Cannon alternate and an AUTO-ATTACK rider, so crediting it on the ability clock is the
face-value credit RM-86 fences. Mel W Rebuttal likewise has its numbers on disk
(`[40, 45, 50, 55, 60] %` OF THE ORIGINAL DAMAGE) but is a fraction of an incoming projectile
no registry can price - the RM-90 S3 assumed-prior class - so 0.0 is correct. Each refutation
asserts both the on-disk numbers AND that the registry carries no entry for that champion.

**DEFAULT-OFF, and the asymmetry with its sibling is deliberate.** `apply_wiki_ability_damage`
ships DEFAULT-ON because it INJECTS a champion with no prior behavior to preserve; this seam
MUTATES a served form, so OFF is the byte-identical contract. Blast radius proven by
construction - a full-snapshot OFF-vs-ON sweep over every champion and key returns exactly one
moved cell, `("Quinn", "R")`. Anti-double-apply: the entry applies only when the target form
has no damage block at all, so a future Meraki re-extract that ships Skystrike makes the
registry silently inert with no code change.

**Verification (fresh this session, measured AFTER the last edit):** DS **9861 passed / 1 skipped / 4661 subtests**;
RC `tests/` **13117 passed / 106 skipped / 460 subtests**; ruff clean across `agents/ tools/ core/ tests/`; the three
ASCII/mojibake/u2500 hygiene modules 15 passed / 7 skipped; doc-size budget 2 passed;
`ds_share_sync --check` in sync at 500 files; zero non-ASCII bytes added (CHANGELOG.md 590 and
CLAUDE.md 29 both unchanged against HEAD); live `:8893` `/health` re-probed at
**1.257.0 / 16.14.1 / 173 champions / 706 items**. All four build-order table families
regenerated against the restarted server across BOTH keyspaces - every diff is stamp lines
only, as a DEFAULT-OFF seam requires.

**Don't-redo:** do NOT author registry entries for Jayce W Hyper Charge or Mel W Rebuttal -
both are refuted with guards on disk. Do NOT re-file the RM-95b residual as a population of 3.
