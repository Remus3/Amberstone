# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25f - three rows closed, two built, and one defect nobody filed (ENGINE 1.249.0)

ENGINE **1.248.0 -> 1.249.0**, patch 16.14.1. Five read-only probe agents in
parallel, then four worktree build agents on disjoint file sets, one Claude as
sole merger. Tier-2 in ritual order: bump by quoted literal (254 files,
`.claude` + `docs/_archive` excluded) -> :8893 restarted -> `/health` re-read
**1.249.0 BEFORE the regen** -> all three build-order families across BOTH
keyspaces -> Share sync (488 files, `--check` green) -> the three ENGINE doc
sites plus the engine `CHANGELOG.md`.

Suites: **DS 9636 passed / 1 skipped / 4617 subtests.** RC `tests/` run fresh
after every doc edit.

## What shipped

| slice | default | headline |
|---|---|---|
| alias/mirror build dedup (UNFILED) | **ON** | 14 cells were shipping FIVE-item builds; 3619 of 3633 cells byte-identical |
| A-07 / RM-82 TERM 2 passive aura | OFF | Mordekaiser ability DPS 11.677 -> 72.155; 14 of 140 rows move; 143 controls unmoved |
| client seam plumb | n/a | both 1.248.0 seams were **0-of-27** on the client path; now Ashe and Quinn move |
| A-26 / RM-95b B1 roster de-cap | OFF | "blocked upstream" was FALSE - it is an RC-controlled roster cap |

## The headline: probing found a bug worth more than any row on the menu

Five of five menu rows were probed before any code. **Three closed without
code** (A-21 S3, A-12 Ranger's Focus, the RM-37/42/38 successor). The largest
win came from a tail observation in a probe report, not from the menu: the build
planner was buying the same item twice under two catalog ids, so Viego and Samira
shipped six-item builds containing five items - in every damage profile, in both
keyspaces, live on disk. Sixth consecutive session where the menu was less
valuable than the probe.

## Three things to carry forward

- **A naive fix can be worse than the bug.** Blind structural id-folding would
  have collapsed `223069` Void Immolation and `443069` Hamstringer - different
  items - onto one identity, suppressing **84 legal Arena purchases**. The
  shipped fold validates identity against the catalog (name OR tags) and keeps
  unresolvable ids distinct. Sweep by ID, never by name, and always check the
  false-positive side of a normalizer.
- **`reference_ds_kit_conversion_not_route_exposed` has a second layer.** Route
  exposure is not reachability: `apply_crit_conversion` and
  `kit_conversion_strength` were parsed by the server AND accepted by the engine
  and still moved **0 of 27** champions, because `core/daemon_slayer_client.py`
  could not forward them. Check the CLIENT, not just the route, on every seam.
- **Four sessions measured an artifact and called it a block.** The A-07 "GAP
  champion and its control are indistinguishable" premise is REFUTED: a
  roster-wide sweep returns 78 distinct top-8 heads, 20 among the 84 AP-scaling
  champions, and the REFUTE control Anivia is already alone in its class. The
  invariance was top-3 stat dominance over a hand-picked 4-champion sample. When
  a measurement repeats identically across sessions, widen the sample before
  concluding the scorer is blind.

## Fences added

- **A-21 / RM-90 is CLOSED at the ally-grant lane.** The ally lane's ceiling is
  993.6 raw HP (amortized 496.8) against a 1700-4800 per-slot self-EHP deficit -
  an order-of-magnitude mismatch, not a coefficient gap. Do not file a fifth
  ally-grant registry row. Successor is the `ds.ehp` champion-sensitivity lift.
- **The carry fight-length map stays hand-curated.** 125 scalar quantities
  scanned, ZERO separate the six members; the one corpus source with sufficient
  n does not reproduce it either. An allow-map entry is an operator meta
  assertion validated by live play, not a threshold.
- **A-12's AS half is CLOSED** and the row mis-names the ability (Ranger's Focus
  is Ashe's Q; her W is Volley). Any future attempt should target the flurry
  AD-amp / on-hit-once asymmetry, not the AS steroid.

## Still open off this session

- **B2** - promote wiki `leveling` to typed damage blocks. B1 shipped, but Locke's
  `baseline_burst` still reads 0.0 and no currently-read feed supplies his damage.
- **A-07 TERM 1** (slow credit / Rylai's) stays blocked: 88 of 161 registered
  champions carry a SLOW entry, so it lifts GAP and control together.

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
