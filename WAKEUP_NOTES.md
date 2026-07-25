# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25e - the four PART-7 survivors BUILT (ENGINE 1.248.0)

ENGINE **1.247.0 -> 1.248.0**, patch 16.14.1. Four parallel worktree agents on
disjoint file sets, one Claude as sole merger. Tier-2 done in ritual order:
bump by quoted literal (256 files / 295 occurrences, `.claude` excluded) ->
:8893 restarted -> `/health` re-read 1.248.0 BEFORE the regen -> all three
build-order families across BOTH keyspaces -> Share sync + the three ENGINE doc
sites. **Stamp-stripped payload diff: SAME on all 9 table files** - correct and
expected, since every seam is DEFAULT-OFF.

**Prerequisite (main thread, `9a33134a`):** `kit_conversion_strength`
route-exposed on POST /rank. `server.py` held ZERO `kit_conversion` references,
so the RM-86 L1 lever was Python-API-only while the shipped tables are generated
through :8893.

**Built (4):**
- **A-12 / RM-46 Ashe** - `_crit_conversion_overrides.py`, DEFAULT-OFF
  `apply_crit_conversion`. IE #8 -> #10, PD #36 -> #30, Yun Tal #11 -> #8,
  ER #7 -> #5; Aphelios byte-identical ON. Her P reads "critical strikes do not
  deal any additional damage", so the 1.15 factor REPLACES the item crit-damage
  sum and IE is INERT on her - stronger than the filing.
- **A-20 / RM-89 Quinn** - both slices. BotRK #1 -> #31, Runaan's #2 -> #41;
  pool 107 -> 109 admitting exactly `{6698, 3179}` via a per-champion
  `marksman_offclass_exempt.json` row.
- **A-03 / RM-81** - `_ability_base_overrides.py` + `abilities.py` hook, six
  champions, exactly 6 of 1033 forms move.
- **A-21 / RM-90 S1+S2** - plumb shipped, **acceptance criterion REFUTED**.

**The refutation to carry forward:** A-21 S1's tank distinct-order count does
NOT move off 1-of-28, in any of 7 keyspace/profile cells, carry control 14/27
both ways. The seam IS live at the RANKING level (Locket #23 -> #6 Alistar,
#20 -> #5 Thresh, Malphite/Ornn/Sion pinned) but never wins a greedy slot -
Leona's last slot has Locket 3116.8 vs Spirit Visage 4389.6 against only +496.8
ally credit. **Order-level movement needs the S3 schema lift, not a coefficient
or a flag. Do not re-attempt S1 expecting table movement.**

**Two honest negatives inside shipped rows:** A-12's Runaan's deny is a
REGRESSION GUARD, not a demotion (Wind's Fury is flat `2 x 55% total AD`, no
crit term). A-20's Stormrazor lead does NOT move (#5 -> #5) - scaled, but its
neighbours fall further.

**Main-thread follow-ons (operator-approved mid-session):** `apply_crit_conversion`
plumbed through `rank_items` + POST /rank to BOTH `compute_dps` call sites, and
`tools/daemon_slayer_build_orders_generate.py` gained the `score_by`
pass-through + `--score-by` flag (the FLAT keyspace the A-21 agent was scoped
out of). Both plumbs SUPERSEDED a test premise and both were repaired, not
suppressed - A-12's helper monkeypatched `compute_dps` and would now silently
no-op, and the prerequisite's Quinn negative control stopped being true once
A-20 seeded her.

**Do NOT redo:** A-16 / RM-82 and A-10 / RM-37+RM-42 stay CLOSED. Do not
re-probe A-21 S1 for table movement. Full record: `docs/OPEN_ITEMS_REVIEW_2026-07-25.md`
**PART 8** + `docs/LEDGER.md` 1048.

---

# 2026-07-25d - ROADMAP budget cleanup + six rows probed, ZERO code shipped

ENGINE stays **1.247.0**, patch 16.14.1. Tree clean, pushed. Commit `b4d1ee56`.
DS untouched, so no Share sync and no table regen this session.

**Done (1):** operator-directed `ROADMAP.md` cleanup, **79443 -> 72052 bytes**,
headroom **9868** against the 81920 ceiling. Relocation only: 16 rows of shipped
narrative / blocked evidence moved verbatim to the `2026-07-25 (cleanup pass 2)`
block at the TOP of `docs/ROADMAP_HISTORY.md`, each leaving a verdict + pointer.
Nothing deleted, no RM id dropped, DS per-champion sweep section untouched
(PROBE HAZARD text). `CLAUDE.md:135` stale "20,190 tests" -> DS 9546 + RC 13061.

**Done (2):** six candidate rows probed read-only in parallel. Verdicts in
`docs/OPEN_ITEMS_REVIEW_2026-07-25.md` **PART 7** + `docs/LEDGER.md` 1047.
CLOSED without code: **A-16 / RM-82 Mordekaiser** (BLOCKED-UNFALSIFIABLE,
inherits A-07) and **A-10 / RM-37+RM-42 Lucian/Akshan** (IE pins at #11 for the
GAP champions AND four controls; the ER dock is intended). Buildable but ALL
FOUR re-scoped: A-03 / RM-81, A-12 / RM-46 Ashe, A-20 / RM-89 Quinn,
A-21 / RM-90 support cohort.

**Do NOT redo:** the ROADMAP relocation, and do not re-probe A-16 or A-10 as
standalone rows. Do not design around "never extract in the same commit as a
regen" - that hazard is UNVERIFIED and roughly contradicts the bump ritual.

**Next:** build the four re-scoped rows. **Prerequisite first:**
`agents/daemon_slayer/server.py` has ZERO `kit_conversion` references, so the
RM-86 L1 lever cannot reach any shipped build table - A-12 and A-20 both need
that route exposure before they can be proven. Any `dps.py` slice inherits
`2d3ddcba` (G2-12 WIP, NOT SHIPPABLE, ENGINE bump owed).

---

# 2026-07-25c - 5 rows named, 3 dissolved, 4 seams shipped (ENGINE 1.247.0)

ENGINE **1.247.0**, patch 16.14.1, DS **9546 passed / 1 skipped / 4547 subtests**,
RC `tests/` **13061 passed / 106 skipped / 448 subtests / 0 failed** (fresh re-run
after the mirror fix). DS `:8893` bounced and `/health` re-read as 1.247.0 BEFORE any
regen. All 9 build-order tables regenerated across BOTH keyspaces and corroborated
STAMP-ONLY by a stamp-stripped payload diff, not by the generator's silent exit 0.
Share mirror 479 files. Full narrative: `docs/LEDGER.md` 1046 + DS CHANGELOG 1.247.0
+ `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` PART 6.

## What shipped (all DEFAULT-OFF, all byte-identical OFF)

- **A-18 / RM-87** resist-to-damage coupling in `ds.ehp`. NEW
  `agents/daemon_slayer/_resist_damage_coupling.py`, 6 machine-swept rows, SORT-ONLY
  credit in `_base_key`. Ornn Thornmail #16 -> #11, Kaenic #6 -> #3, Warmog's #2 -> #7.
  Poppy negative control byte-identical ON.
- **A-31 / R67** Terminus SR `3302` Light-side resists, 18 / 21 / 24 at L1 / L11 / L14.
  Arena `223302` REFUSED - no on-disk feed carries its magnitude.
- **A-08 / RM-35 clause 2** `exclude_off_axis_items` extended to the CARRY route.
- **A-39** boot-utility CC input replaces the AP-share proxy.

## The headline: the mis-file rate did not fall, and the reason changed

Three of the five rows the prompt named dissolved under probe (A-27 and A-30 already
shipped, A-11 unfalsifiable), so two replacements were pulled. **9 mis-files caught
before code across three sessions.** These were not bad research - they were STALE
research: A-27 was closed 1 day before the row was written, A-30 thirteen days before,
and A-31's "needs a schema lift" blocker had been false for eight. A tier records how
well a row was probed, never how recently.

## Two traps that bit again

- The `item_ids=[]` artifact manufactured its FOURTH false headline (A-08's "BotRK #1
  for Miss Fortune"; at real depth the leads are Runaan's / LDR / Terminus).
- A slice reported "+1 line in `ehp.py`" and the 3-line anchor matched TWICE in the
  file. Merging by file copy would have been wrong either way - the fix was to confirm
  only one real `item_resist_grants` call site exists before applying it.

---
