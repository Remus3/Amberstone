# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21c - R151 HEXCORE OFFLINE EXPLORER RE-SYNC (gemini headless loop, cycle 3) - NO ENGINE CHANGE

**Tier-0/docs run.** LEDGER 990. Slice merge `79c3deba`. ENGINE-IMPACT NONE - no DS math
path, no ENGINE bump, no Share churn, no restart.

## What shipped

`docs/HEXCORE_offline.html` re-synced against the repo. 3 missing dust leaves added
(`dashboard/_lcu_inprocess.py` -> `m_dashserver`, `lcu/champ_select_shape.py` -> `m_lcupre`,
`lcu/snapshot_shape.py` -> `m_lcupost`), dust 322 -> 325 at all four sites, ENGINE tooltips
1.232.0 -> 1.233.0 / 9087 tests, LEDGER node desc entry 903 -> 989, repo-stats HUD
re-anchored to `eb111c36` / 2026-07-21 / commits 3789. Guard test
`tests/test_hexcore_offline_dust.py` `EXPECTED_NEW_BASENAMES` widened 26 -> 32.

## The directive assumed a cold sync; the real gap was 3 files, not 32

45 net-new `.py` adds since `d584e02e`, minus 13 `Share/src/agents/daemon_slayer/*.py`
byte mirrors = 32 real files - and R138 had already landed 29 of them. Grounding this
BEFORE dispatching turned a 32-file rewrite into a 3-entry append.

## Both gates earned their keep

The **verifier** caught that the slice agent finished both edits but never committed:
branch had zero commits, `main...HEAD` empty, so a naive merge would have been a silent
no-op reporting success. The **5-phase fixture audit** caught two number defects the
verifier did not: the ENGINE tooltip took the COLLECTED DS count (9088) where the repo
convention for that anchor is the PASSED count (9087, per `docs/DAEMON_SLAYER.md`) -
which also called a skipped test green - and advancing the engine/ledger rows to
2026-07-21 left the neighbouring repo-stats rows on a 2026-07-20 snapshot, so the HUD
contradicted itself. Both fixed in-slice before push. Zero MUST-FIX.

## Don't-redo

HEXCORE dust set is CLOSED against `d584e02e..eb111c36`. `Share/src` mirrors stay
EXCLUDED (byte-identical duplicates would double-render their parents' clusters). Do not
"correct" `snapshot_shape.py` -> `m_lcupost`: the DUST parent convention is decorative
round-robin, not semantic (`lcu_rune_writer.py`, a pre-game module, is parented
`m_lcupost` too). The 8-10px type in `#hexcore-stats` is correct for a zoomable canvas
doc; the v2.1 `--fs-xs` floor governs the dashboard, not this offline artifact.

---

# 2026-07-21b - R150 CONQUEROR 8010 OFFENSE GRANT (gemini headless loop, cycle 2) - ENGINE 1.233.0

**Tier-2 engine run.** LEDGER 989. Pushed `774ed236..7dfa003b`. ENGINE 1.232.0 -> 1.233.0.
Slice merge `a7c5f9db`, engine-tail commit `7dfa003b` (267 files).

## What shipped

Rune 8010 Conqueror credited into the EXISTING `agents/daemon_slayer/_rune_offense_grants.py`
registry behind the EXISTING `apply_rune_offense_grants` seam. No new module, no new flag.
Magnitudes at the default 12 stacks: **AD 12.96 (L1) -> 28.8 (L18), AP 21.6 -> 48.0**.

## The directive was mostly wrong and the audit ran BEFORE any code

7 target runes named; 6 were not work. 8236 + 8233 already shipped in R145. **8138 Eyeball
Collection, 8136 Zombie Ward, 8120 Ghost Poro are NOT IN the 16.14.1 `runesReforged.json`
at all** (removed from the game). 8210 Transcendence is Ability-Haste-only, settled inert.
The feed path the directive cited does not exist (real one is
`data/meta_build/ddragon/16.14.1/runesReforged.json`), and the new module + new flag it
specified would have duplicated the shipped lane.

## An adversarial slice refuted MY OWN brief mid-run

I told the builder to mirror `enemy_runes.py:149` at 21.6 -> 48.0. That is correct ADAPTIVE
FORCE but **AF IS NOT AD** - the enemy lane uses AF as a raw damage proxy, never as a stat.
Riot converts 1 AF = 1 AP **or 0.6 AD**, so my brief would have inflated the AD column by
**1.667x**. Caught pre-merge, corrected in-slice. The 0.6 ratio is pinned by a property test
against the registry's OWN rows (`round(0.6 * ap) == ad` on all 7 stated values), not by an
asserted constant. Same refutation also forced the stack count to become a KNOB
(`_ASSUMED_CONQUEROR_STACKS` + per-call `conqueror_stacks`, clamped 0-12) per
`rune_procs.py:212`, and killed the enemy-lane precedent citation because max-stacks flips
from conservative (threat lens) to optimistic (self lens).

## Traps hit this run - read before the next DS bump

1. **THREE build-order generators, two keyspaces.** FLAT `data/daemon_slayer/<patch>/` <-
   `tools/daemon_slayer_build_orders_generate.py`; NESTED HZ-B
   `data/daemon_slayer/build_orders/<patch>/` <- `core.build_order_precompute`; variants <-
   `core.build_order_variants`. **The stamp tests read the NESTED ones.** All need
   `--champions all`. I regenerated the flat set first and stayed red.
2. **TWO changelogs.** `test_changelog_tracks_engine_version` reads
   `agents/daemon_slayer/CHANGELOG.md` (bare `X.Y.Z (date` format), NOT `Share/CHANGELOG.md`
   (`## X -> Y (date)`). I edited Share first and stayed red. Both need an entry.
3. **`data/rewind_history.db` is gitignored**, so `git worktree add` never copies it and 27
   db-backed tests SKIP in any worktree (plus 2 for absent 1440p HUD profiles). That is the
   whole of the 29-test "passed -> skipped" delta a worktree slice will report. Not a
   regression. Confirmed by the skip count returning to 23 on main.

## OWED - real finding, not absorbed silently

**The FLAT Arena build-order table on main is five engine versions stale** (last written by
`1f13188b` at ENGINE 1.228.0; engine is now 1.233.0). Regenerating it changes 365 lines of
item ids - a material change to live Arena recommendations. Proven NOT caused by this slice
(`apply_rune_offense_grants`/`rune_ids` appear in neither generator, so the entry is
unreachable from build-order generation) and proven deterministic (two consecutive regens
content-identical). The three flat tables were REVERTED rather than ride into an engine-bump
commit. **Needs its own slice with its own validation.**

## Loop health

Cycle 2 breached its 5400s deadline at 03:13:51 - build subagent ~60 min, verifier ~29 min.
Controller injected stall recovery and extended once; no STOP. Not a hang.
`ops/loop/control/blocker.txt` on disk is STALE R145 text - do not read it as current.

## Don't-redo

Offensive-rune sweep is CLOSED for the 16.14.1 feed. Every remaining offensive rune is a
dead id, an AH-only rune on a settled-inert axis, a move-speed rune, a proc-damage rune
already scored by the burst consumer, or 8232 Waterwalking (uptime-blocked, no positional
signal). A further pass needs a role/positional signal, not another sweep. Do NOT model
Conqueror at a fixed 12 stacks. Do NOT mirror `enemy_runes.py` magnitudes into a STAT
registry without the AF conversion.

---

# 2026-07-21a - R149 SHARE FOLDER OVERHAUL (gemini headless loop, cycle N) - docs only

**Tier-0/1 docs run, ENGINE-IMPACT NONE.** LEDGER 988. Pushed `d4070710..dfb509b8`.
`Share/` re-presented as an external product artifact across FOUR disjoint worktree
slices (Claude sole merger, `verifier` subagent gate before every merge).

## What shipped

- **README** - external product page: problem framing, at-a-glance / contents / docs
  tables, a **Data sources and credits** section (Riot Data Dragon, CommunityDragon,
  Meraki/lolstaticdata, LoL wiki + attribution notes), an honest **Limitations** block.
- **docs 01-05** - net -294 lines. `04` -285 (registries + kit axes -> two tables),
  `05` -81 (stale audit residue cut). `02` gained the missing 7th-scorer section
  (`onhit_dps.py`); `03` gained per-provider credits + two corrected facts.
- **CHANGELOG** - 2737 -> 1079 lines, **105/105 release entries + dates preserved**
  (verifier diffed the semver token sets independently; zero new range compression).
- **MANIFEST template** - `tools/ds_share_sync.py` `_manifest_body()` split out under
  TDD; the GENERATED file now carries a product intro, `## Package stamp`,
  `## Generated vs authored`, and `## Where to start`.

## The two things worth remembering

1. **`Share/MANIFEST.md` CANNOT be hand-edited.** `_stamp_manifest()` regenerates it
   wholesale and the pre-commit hook re-runs the sync, so a hand edit is silently
   reverted with no error. Change the template in `tools/ds_share_sync.py` instead.
   `--check` deliberately excludes MANIFEST, so this never fails CI - it just vanishes.
2. **The verifier gate caught three factual defects the slice agents missed in their
   own work:** stale suite counts (8866/339 -> 9054/349), a wrong standalone error
   count (170 -> 179), and a documented reproduction command that aborts at collection
   and runs ZERO tests without `--continue-on-collection-errors`. All fixed pre-push.

## Carry-forward

- New disclosure now IN the package: it does not run its own suite clean standalone
  (8677 passed / 108 failed / 179 errors) because 60 of 349 test files reach outside
  it; the other 289 pass clean (6666 / 1915 subtests). Closing that boundary gap is
  unclaimed work, not scheduled.
- The `gist_share_sync` post-commit index corruption fired in 3 of 4 worktrees (up to
  4748 phantom deletions). Every agent caught it via `git show --stat` + plain
  `git reset`. Nothing phantom entered a commit. Guard still needed on every run.

Gates: `ds_share_sync --check` green (1.232.0, 501 files), RC **12470 passed**,
DS **9054 passed / 3582 subtests**, `ruff check .` clean.
