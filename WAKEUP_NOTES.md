# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-26l - RM-117 cohort bands CLOSED, RM-91 SHIPPED (ENGINE 1.258.0), repo md cleanup. 9 commits.

**IS a DS session.** ENGINE 1.257.0 -> 1.258.0, Share mirror regenerated, `:8893`
bounced and live-probed, both build-order keyspaces regenerated.

## The hand-off task closed, but not for the predicted reason
`build_rank_baselines` finished at **30 cohorts, not 31** - MASTER logged
"no accounts resolved - SKIPPED". The file landed and the absent-baselines warning
went away, but all 14 metrics still read "no cohort table". **The real defect was a
producer/consumer shape mismatch, not a missing file:** `cohort_baseline.load()` did
`.get("roles")` at the TOP level (the single-cohort shape) while the renderer defaults
to `rank_baselines.json`, which is `{"tiers": {COHORT: {"roles": ...}}}`. It returned
`{}` and every band was omitted silently. Fixed with `--cohort`; a tiers-shaped file
with no cohort named now RAISES and lists all 30 (`ecf59a29`).

**Then reading the now-working output found a worse bug.** `rank_of` kept the LAST
threshold a value cleared, so on a metric where p10..p90 are all 0.0 a 0.0 cleared
every band and kept p90 - a TOP laner who healed nobody was told they were 90th
percentile. Three of fourteen live metrics were wrong. Ties now take the LOWEST
percentile sharing the threshold plus a `tied` marker (`ec4d1e15`).

## RM-91 shipped, and the filed row was wrong about its own size
Population is **11 tank-routed champions, not the 5 filed**. Sett and Sion are
REFUTED - they scale off the TARGET's health. Built by a worktree agent, merged by
Claude, every claim re-verified independently (all 11 seeded values re-derived,
DS suite re-run 9900 passed, seam live-probed on `:8893`). **The double-count trap is
the thing to remember:** most of these kits emit sub-component AND Total blocks for
one ability (Sejuani W 4.0 + 8.0 with a Total of 12.0 that IS their sum), so a naive
sum triple-counts. **KNOWN LIMIT, pinned as a test:** T1 is monotone in `delta_hp`,
so it does NOT fix the Randuin's headline - that needs T2 (the item's own caster-HP
proc), which is unbuilt.

## RM-118 filed - and "file it as RM-99" would have been a collision
RM-99 was already allocated 2026-07-19 and shipped as `assume_item_health_stacks`.
**TWO id-allocation lines were stale** (ROADMAP said next-free RM-99, the tracker said
RM-105); both corrected to RM-119, and the tracker now says to check ITSELF, never
ROADMAP prose, before taking an id. RM-118 is mana-as-damage on `/rank-tank`,
population exactly 1 (Blitzcrank). Kassadin and Ryze are NOT defects.

## Repo cleanup - the inventory agent was wrong twice and counting caught both
27 orphans archived by `git mv`, each verified individually. That check saved a
`proposal.md` and a nested `README.md` (basename collision with root README), and
refuted the "archive the P0..P6 set" recommendation - 8 of 9 still carry 2-7 inbound
refs. 11 `.claude/commands/*.md` had ZERO version control and are now tracked.
ROADMAP gained a "WHERE WORK LIVES" table; three rival "single source of truth"
claims scoped.

## Do NOT redo / traps that cost time this session
- `agents/agent6_auditor/reports/` LOOKS dead but `_supervisor_ephemeral.py:86` writes
  failure stubs there. It is live.
- `docs/_archive` is gitignored yet its ~300 files are TRACKED. Archive with `git mv`
  ONLY - `cp` + `git add` silently fails and can drop a file from version control.
  Now recorded in `.gitignore`.
- DS champion-coverage: count from the nested `champions` key. A flat top-level count
  returns 2. The doc's old "196 entries / 125 champions / 73%" was that mis-parse plus
  block_index's own count mistaken for the distinct total. **True: 132 champions / 167
  entries / 77.2%.**
- **Share has THREE doc sites.** README got the 1.258.0 note, CHANGELOG.md was missed,
  and `ds_share_sync --check` reads GREEN anyway because it deliberately does not
  rewrite changelog history.
- An ENGINE bump REQUIRES regenerating BOTH build-order keyspaces. Diff should be
  exactly 2 lines per file (engine_version, generated_at) - that is the byte-identical
  proof for a DEFAULT-OFF lever.
- The "tracked tools/ copy always wins" mirror rule was WRONG and had preserved the
  ADR-012-decommissioned bridge in `done.md` for a month. Corrected in sync-all-md
  section 9: promote the NEWER side, ASCII-clean it, and normalize glyphs BEFORE
  diffing or the s244 em-dash purge hides whether content actually diverged.

## OPEN, not started
- **Share standalone has 13 REAL failures** (7832 passed / 13 failed). None is an
  engine failure - each opens a CWD-relative path that exists only at the source-repo
  root. They are host-dependent by exactly the `_HOST_DEPENDENT_TESTS` definition and
  were never added to it. Documented in `Share/README.md`, NOT fixed. Fix = anchor on
  `__file__`; excluding them would drop 13 files of real coverage.
- RM-91 **T2** (item's own caster-HP proc) - the half that actually fixes Randuin's.
- RM-118 build (mana axis, population 1).
- `objective_participation` REFUTED verdict is recorded in LEDGER but
  `docs/REPLAY_T2_PARSE_CRITERIA.md:309` still has the sign backwards ("would inflate
  these rows" - measured, it DEFLATES them), plus two ELITE_MONSTER_KILL field-list
  corrections (`assistingParticipantIds` carries ENEMY participants; `monsterSubType`
  is DRAGON-only).
- MASTER cohort missing from `rank_baselines.json`.

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
