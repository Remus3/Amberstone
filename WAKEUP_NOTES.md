# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-26c - the Share package's green-suite promise was false (R192, gemini loop cycle 2)

Commit `f26f651c`. No ENGINE bump, no DS bounce, no RC restart. Share mirror
regenerated (492 -> 494 files), `ds_share_sync.py --check` green.

Directive: unit (b) - read the ENTIRE `Share/` folder end to end and update /
clean / prune it as a new external presentation.

**Unit (b) has now run four times (R139 / R163 / R166 / R189 / this one), and
the two findings that mattered came from something no prior pass did: running
the package's own advertised quickstart.** `Share/README.md` promises the
shipped suite "exits green offline with no flags ... 0 failed, 0 errors, exit
code 0". It exited **1, with 4 failures**. For a package whose product IS a
runnable artifact, prose-checking cannot surface an exit code.

Two root causes, one bug class - the mirror shipped consumers without their
dependencies:

1. `tools/ds_feed_index.py` was not in the generator's `_DS_TOOLS`, so
   `test_artifact_patch_marker_guard.py` (landed `b23b5f16`, ENGINE 1.243.0 -
   after the last audit) raised `FileNotFoundError` on a path-import.
2. `web/data/champion_aliases.json` was unmirrored while the mirrored
   `tools/daemon_slayer_extract.py` reads it at MODULE IMPORT time. So a tool
   the package advertises as a shipped offline extractor could not be imported
   inside the package at all. That is the worse of the two, and the failing
   test is only how it surfaced.

Fixed at the generator (`_HOST_ASSET_FILES`, exact-path match, asset mirrored
at its identical repo-relative path), NOT by adding the test to
`_HOST_DEPENDENT_TESTS` - that would have gone green while dropping a real
engine guard and leaving the extractor broken. Guarded by a new failing-first
PROPERTY test, `tests/test_ds_share_mirror_self_contained.py`, which pins
self-containment rather than the two incident filenames.

**A premise in my own brief was measured and refuted.** I told slice C that
fourteen versions of RM-115 seam-wiring had probably made `docs/04`'s "no
caller can switch it on" rows stale. It re-probed every one: all still hold.
`docs/03` needed zero edits - all 22 mirror files, every size, every embedded
count correct. A no-change verdict backed by probes is the point.

Countable drift corrected: test files 309/358 -> 331/386, boundary set 49 ->
55, engine modules 106 -> 112, flag matrix 47 -> 55 names (tri-state 1 -> 4),
DS suite 9238 -> 9746, "the fourteen most recent" releases listed fifteen; 148
of 342 `file:line` citations re-anchored, 0 broken symbols; the generated
engine `__init__` docstring said six archetypes when there are seven.

Suites, all re-run by the merger after the last edit: Share package **7729
passed / 16 skipped / 3109 subtests, exit 0**; DS **9746 / 1 / 4653**; RC
`tests/` **13118 / 106 / 460**. ruff clean, 0 non-ASCII across every authored
Share file, six worktrees removed after confirming 0 unmerged each.

**Next Share pass: run the quickstart FIRST, then re-measure the countables.**
Do not re-read the prose top-to-bottom - both real findings this round came
from the exit code and from `find | wc -l`, not from reading. Two residuals
left deliberately: `ds_feed_index.py`'s CLI still imports a repo-side `tests/`
module so it cannot run inside the package (import and `KNOWN_STAMP_LAG` are
fine), and `test_abilities_content_freshness.py` may now be re-admittable to
the mirror but has a second host reach - that should be a measured decision,
not a side effect.

---

# 2026-07-26b - HEXCORE offline sync, and the debt was 9 not 54 (R191, gemini loop cycle 1)

Tier-0 presentation artifact. Commit `b4df6494`. No ENGINE bump, no DS bounce,
no RC restart, no Share sync.

Directive: re-sync `docs/HEXCORE_offline.html` against the net-new non-test .py
files added since `d584e02e` (2026-07-14).

**The measurement was the work.** `git diff --diff-filter=A d584e02e..HEAD -- '*.py'`
returns 297 files. Drop `Share/` (74 - byte mirrors of repo-root modules) and
`tests/` (223 - "non-test" is the unit's own wording) and 54 real source files
remain. **45 of those already had DUST leaves from the R138 pass**, so the real
debt was **9**. Adding all 54 would have made 45 duplicate particles; the guard's
`test_no_duplicate_dust_entries` catches that, but only after the edit.

Shipped: 9 leaves (parents from the existing DS spread - `m_dsengine`,
`m_dsserver`, `m_dsclient`, `ds`, `daemonslayer`, `m_buildorder`, `t_dsextract`),
dust 341 -> 350 across all four cross-asserted count sites, and a stats HUD
re-anchored to ground truth: ENGINE 1.240.0 -> 1.254.0, 9238 -> 9746 DS tests,
commits 3931 -> 3972, last `686a4b48` 2026-07-25, LEDGER high-water 997 -> 1054.
The same stale ENGINE pair sat in the `DAEMON_SLAYER.md` NODE description too -
a sweep that reads only the HUD tooltip misses it.

TDD RED-first (`EXPECTED_NEW_BASENAMES` 45 -> 54 before any HTML edit). Verifier
subagent CONFIRM on all 5 claims, re-deriving the missing set from git itself and
re-running `node --check` on the extracted 957k-char script block; it caught a
stale comment in the guard's own docstring (20/2 claimed vs 74/223 actual), fixed
in-slice. Rendered probe taken anyway (edit lands inside an inline JS literal):
0 console errors, HUD reads `dust: 350 files` / `engine: DS 1.254.0`.

Suites fresh after the last edit: **DS 9746 passed / 1 skipped / 4653 subtests**,
**RC `tests/` 13110 passed / 106 skipped / 460 subtests**. Guard 11/11, ruff clean,
0 non-ASCII.

**Next pass must re-derive its own delta** (`git diff --diff-filter=A <last-synced-sha>..HEAD`
minus `Share/` minus `tests/` minus basenames already in the DUST literal) and must
NOT trust a count carried in a directive.

---

# 2026-07-26a - RM-115 CLOSED, and the last four pairs are declines (ENGINE 1.254.0)

ENGINE **1.253.0 -> 1.254.0**, patch 16.14.1. Two read-only spec agents in
parallel over the eight tail routes, then the wiring applied in the main thread
(one file - worktrees would only have made merge work). One build agent wrote
the acceptance test. Tier-2 in ritual order: bump by quoted literal (126 files /
154 occurrences) -> :8893 restarted -> `/health` re-read **1.254.0 BEFORE the
regen** -> both build-order families across both keyspaces -> Share sync (492
files, `--check` green) -> all four ENGINE doc sites **plus the two Share
release notes `--check` cannot see**.

Suites, both measured fresh AFTER the last edit:
**DS 9746 passed / 1 skipped / 4653 subtests.**
**RC `tests/` 13110 passed / 106 skipped / 460 subtests.**

## The headline is the DECLINE, not the drain

**Per-route stranded debt 25 -> 4. Name-collapsed 12 -> 2.** 21 pairs wired
across six client functions (`/burst` 7, `/dps` 6, `/rank-assassin` 4, `/rank`
2, `/ability-dps` 1, `/rank-mage` 1).

The session prompt framed `/beam` and `/v2/fight-report` as "a design call, not
wiring". The answer is **DECLINE for both**, and that is the durable output of
this session:

- `/v2/fight-report` has **ZERO callers repo-wide** - the literal appears only
  in its own docstring, the dispatch table, `docs/DAEMON_SLAYER.md`, the
  CHANGELOG and the two ledgers, and both of its tests call
  `compute_fight_report` in process. Served, never requested.
- `/beam` has ONE live consumer, `coaches/sr_draft_profile.py`, which holds its
  own HTTP call for reasons a migration must break: a 4.0s budget against this
  client's deliberate 0.5s `DEFAULT_TIMEOUT` fail-silent contract, and a
  two-value error channel that `_post_json`'s None collapses. And the seam is
  **arithmetically inert** for it - `mode="SR"`, and no champion carries an
  `sr` key in `wiki_stats.json`.

**The ledger's honest end state is 4, not 0.** Both declines carry an inline
re-open condition. A future session that reads 4 as debt and wires it will
re-introduce the exact reachable-and-dead illusion RM-115 existed to kill.

## What generalises

**The transport trap fired a third time, on a NEW key.** `/burst` parses
`runes` - **NOT** the EHP family's `rune_ids` - plus `caster_current_hp_pct`.
Neither is seam-prefixed, so neither guard sees them, and without them BOTH
`gate_*` seams are reachable-and-dead (measured byte-identical with `runes`
omitted). Same concept, different key per route: the 1.253.0 wiring did not
carry over.

**The gates are HONESTY gates and the direction inverts.** OFF applies the rune
amp unconditionally, so turning `gate_target_hp_amp` ON against a full-HP target
correctly REMOVES Coup de Grace's amp (716.343 -> 663.281). A test asserting
"ON is bigger" would have been wrong.

**Two silent traps on `/rank-assassin`, one of them the client's own default.**
`assume_squishy_target` is disabled by any positive `target_armor`
(`burst.py:2018`); the Collector arm of `assume_takedown` is disabled by
`target_max_hp=0.0` (`burst.py:1075`), which IS `rank_assassin_for`'s default -
so the seam reads half-working rather than misconfigured.

**`top` is a load-bearing transport.** `exclude_off_axis_items` REMOVES rows
rather than reordering them, and on an auto-attack scorer every removed row is
deep: Jhin is byte-identical at the client default `top=8` and only moves at
`top=200`.

**`apply_mode_modifiers` on `/rank` has two lanes and only one can reorder** -
the URF multiplier lane scales uniformly (Jhin top row x1.01, all 214 rows hold
order); the ar/swift addend lane does reorder.

## Judgement calls worth knowing about

- **`assume_magic_burst` was NOT deleted**, against the spec's recommendation.
  The route is right and the client is wrong, but the parameter is load-bearing
  across `archetype_dispatch`, `routes_state` and four test files. Resolved by
  making the lever reachable on the route that DOES parse it,
  `burst_for(assume_magic_burst=...)`, and filing the dead one.
- **One pre-existing test broke and was re-expressed, not relaxed.**
  `tests/test_ds_client_conversion_seam_plumb_w2.py` asserted the two W2 seams
  are the FINAL TWO parameters of `rank_for` - stricter than the convention its
  own docstring cites, and false for any correct append. Replaced with the
  property the convention actually protects (only the three genuine inputs may
  lack a default; both seams KEYWORD_ONLY with defaults; both after `timeout`;
  relative order preserved), which is strictly stronger.
- **The committed `build_order_variants_*` tables were STALE.** Six of nine
  tables are byte-identical after stamp-stripping; the three variants tables
  moved. Proven NOT attributable to this change by regenerating against the
  PRE-change client and getting byte-identical output to the post-change client,
  with both differing from the committed table.

## Filed, not fixed (each has real blast radius)

1. The dead `rank_assassin_for(assume_magic_burst=...)` parameter.
2. `rank_for` likewise emits `assume_passive_as_stacks` and `apply_target_vuln`
   into a `/rank` body that never parses them.
3. `rank_for_primary_archetype` has no pass-through for the 21 new kwargs, so no
   live coach tick can flip one yet. All 21 are DEFAULT-OFF, so nothing regresses.

## Ops note

`Get-NetTCPConnection -LocalPort 8893` matches lingering **TimeWait** sockets
(`OwningProcess = 0`), which reads as "port still bound" when DS is fully down -
and `taskkill /F /PID 0` fails as a critical system process. Filter on
`-State Listen`. Memory updated.
