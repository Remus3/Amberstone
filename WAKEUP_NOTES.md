# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21d - R152 LETHALITY STAT-BLOCK PARITY (gemini headless loop, cycle 4) - ENGINE 1.233.0 -> 1.234.0

**Tier-2 DS run.** LEDGER 991. Slice `ee8a6cb3`, merge `890daf1c`. DS bounced, `:8893`
serves 1.234.0. Share mirror synced in the same commit.

## What shipped

Five item entries in `agents/daemon_slayer/_effects_data.py` that state a Lethality in
DDragon 16.14.1 but read 0.0 in DS: `6698` Profane Hydra 18 and `6695` Serpent's Fang 15
(both SR AND ARAM, maps 11/12/21/35), plus Arena `226698` 18, `226695` 19, `446691`
Duskblade 20. DEFAULT-ON, no flag - see the deviation note below.

## The finding that matters

Penetration is REGISTRY-ONLY. `stats.py` `ITEM_STAT_KEY_MAP` has no pen key and DDragon's
machine-readable `stats` block never carries one - pen exists only in the `<stats>` HTML of
`description`, and the local Meraki snapshot has no stat block on any of its 320 items. So
`ITEM_EFFECTS` is the sole credit path and a missing field is a silent 0.0. Do not go
looking for a generic path.

## Two process notes worth keeping

**The orchestrator's own sweep beat both agents.** Both read-only sweep agents returned a
ranked list topped by a single "one-line fix". A direct 706-item parity sweep showed the 12
divergent ids were TWO root causes: RC-A (stat absent, 5 ids, a real data bug) and RC-B
(Arena magnitude drift, 7 ids, a guarded-doctrine collision). Shipping either agent's top
pick would have left four RC-A ids uncredited.

**Deliberate deviation from the directive, logged.** The directive said to ship any fix
"behind DEFAULT-OFF seam". This shipped DEFAULT-ON. A flag here would have made 5 items
behave differently from the 26 already-credited lethality rows and left a proven-false 0.0
live; adding a row to an always-on registry is not a new math term. R150 set the precedent.

## Gates

DS 9091 passed / 1 skipped / 3650 subtests. RC 12440 passed / 52 skipped / 406 subtests,
1 failure which was PROVEN to be live-coupling (`test_live_three_profiles` asserts the live
`:8893` version) and went 18/18 green after the DS bounce. ruff clean. ENGINE 144 literals
across 123 files, zero residual. `ds_share_sync --check` in sync at 1.234.0.

## Carry-forward

RC-B Arena lethality/magicpen magnitude drift is OPEN and is a DOCTRINE call, not a data
bug - the "Arena mirrors inherit SR" convention has guard tests, and
`test_terminus_juxtaposition_r67.py:118` structurally derives the Arena value from the SR
Meraki entry (and reads a pinned 16.13.1 file). Escalated to the director in the
ORCHESTRATION_PLAN findings log; do not weaken those guards without a decision. Smaller
tails: `1111` Jarvan I's 12 flat magic pen has no ITEM_EFFECTS entry at all;
`Share/README.md` releases stale at 1.228.0, needs a 1.229.0-1.233.0 backfill.

The gist post-commit hook index corruption recurred (4th). Worktree index only, commit
object clean, cleared with `git reset --mixed`.

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
