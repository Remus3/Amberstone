# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

# 2026-07-25 - five open-item rows probed, three built, three mis-filed (ENGINE 1.245.0)

HEAD after this session: see `git log -1`. ENGINE **1.245.0**, patch 16.14.1,
DS **9446** / `tests/` **12987**, DS `:8893` bounced and verified serving 1.245.0
BEFORE any regen. Full narrative: `docs/LEDGER.md` 1044.

## What shipped

- **A-04 / RM-99b Heartsteel cadence, SR ON / Arena OFF** (operator call). SR 3084
  corrected to the real 30s per-target gate directly in `_effects_data.py`; Arena
  223084 held at 3.5 because 30s is unsourced on its own feed. Filed 8.5714x was
  EXACT. The over-credit was supplying **13-32 pct of total credited auto DPS** on
  shipped bruiser builds. SR occurrences 135 -> 6, ARAM 156 -> 27.
- **A-29 / R129 Viego R** surplus-block MERGE, DEFAULT-OFF `apply_cdragon_surplus_ad`.
  0.000 -> 1.169 DPS. Population is **1 champion, not 6**.
- **A-01d seam forwarding.** `/api/ds-preview` reached zero of nine seams; and the
  `with_build_order` branch RANKED with `prefer_kit_axis_by_win` ON and PLANNED with
  it OFF. Both sides now pinned to agree.
- **A-40(1): the first Family A staleness guard** - which immediately caught a live
  bug (below). The row's "OPEN DESIGN Q" was stale; already answered in LEAP-04.
- **Arena mirror-id dock gap, DEFAULT-ON.** `kit_synergy.py` matched spellblade items
  by SR id only, so the carry coherence dock was **inert in Arena**: Essence Reaver's
  mirror 223508 sat at slot 1 for 6 carries. 18 -> 0.

## Three things that would have shipped wrong

1. **Three of five rows were mis-filed, in two recurring classes.** A row whose answer
   already existed on disk (A-40's design Q, answered in LEAP-04 with
   `UNVERIFIED-SKIP count: 0`), and a row describing INTENDED behavior as a bug
   (A-24 / RM-93 - the deny is deliberate and test-pinned, and the "modelled damage
   formulas" the row cites as evidence are the REASON for it). Both closed with no
   code. **Probe the row before building it.**
2. **The A-04 fix invalidated its own test.** The magnitude test anchored on Aatrox's
   shipped SR build and asserted Heartsteel was in it - then the fix evicted Heartsteel
   from that build (Aatrox now takes Randuin's 3143). The guard fired correctly; the
   anchor was self-defeating. Never anchor a measurement on the engine still
   recommending the thing you are about to demote.
3. **The ENGINE literal count read 1442, not ~372.** The excess was five live agent
   worktrees, each a full repo copy. A blind repo-wide replace would have rewritten
   `ENGINE_VERSION` inside all of them. Real count excluding `.claude` is 241.

## Standing hazards for the next session

- **Keyspace 2 was MORE stale than keyspace 1** (195 vs 135 Heartsteel occurrences),
  vindicating LEDGER 1043's doctrine one session later. A regen is not done until all
  three families across BOTH keyspaces have run.
- **Share sync must run AFTER the CHANGELOG entry**, not before. It ran twice this
  session because of that ordering; the determinism test caught it.
- **`3131` Sword of the Divine is a NEW open residual:** `every_n_seconds=15.0` against
  a 90s active cooldown in its own DDragon text, uncited 6x over-credit, absent from
  Meraki. Same operator-gated class as A-04. Not yet filed to a row.
- **Zeri's Arena cell is flagged, not accepted:** the dock fix changes 4 of 6 slots and
  trades the ER artifact for Liandry's + Dusk and Dawn, which is the AP-on-AD-marksman
  class `coherence.py:138-139` already defers. The eviction is right; the replacement
  is not clearly better.
- CLAUDE.md's **"20,190 tests" is stale** against the measured `tests/` count (12987).
