# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25g - five probes, one answer: the seams do not reach production (ENGINE 1.250.0)

ENGINE **1.249.0 -> 1.250.0**, patch 16.14.1. Five read-only probe agents in
parallel on five DIFFERENT menu rows, then three worktree build agents on
disjoint file sets, one Claude as sole merger. Tier-2 in ritual order: bump by
quoted literal (132 files, `.claude` + `docs/_archive` + `Share` excluded) ->
:8893 restarted -> `/health` re-read **1.250.0 BEFORE the regen** -> both
build-order families across both keyspaces -> Share sync -> all four ENGINE doc
sites.

Suites, both measured THIS session after every edit:
**DS 9686 passed / 1 skipped / 4646 subtests.** RC `tests/` re-run fresh at the
end (first pass 13106/106/460 with 4 known-cause failures, all repaired).

## The result that matters

**Five probes, five different rows, one shared finding that nobody had filed.**
A DS seam has THREE gates - engine kwarg, HTTP route parse, and
`core/daemon_slayer_client.py`. Census over `server.py`: **43 route-parsed
seam-shaped kwargs, 9 expressible through the client, 34 default-OFF and
stranded.** The client is the chokepoint every generated build table and every
live coach tick passes through, and none of `rank_for` (24 params),
`rank_tank_for` (15) or `rank_for_primary_archetype` (40) carries `**kwargs` -
verified by `inspect.signature`, not grep. `core/build_order.py`'s own docstring
says its `rank_fn` takes none either, so nothing can be smuggled via
`rank_kwargs`.

This re-scopes **A-28 / RM-14**, filed as default-OFF levers awaiting an
operator decision: even if the operator decided, there is no wire. Filed as
**RM-115** with a 4-item priority list.

Named casualties: `apply_ability_base_overrides` (RM-81's six ability-base
corrections, chosen BECAUSE they move a ranked order) is 0/0/0, reachable only
from its own test; `apply_passive_aura_damage` shipped LAST SESSION at 1.249.0
and was already dead at gate 3; `_kit_penetration.py` (15.9 KB, ENGINE-bumped)
has ZERO production callers; `kit_conversion.py` reaches **1 of its 9 curated
champions** because `hybrid.py` has zero occurrences of the kwarg.

Guarded going forward: `test_route_seams_reach_the_client.py` collects the
route-parsed seam set by introspection and carries the stranded set as an
explicit debt ledger - GREEN today, RED on any new route seam without a wire.

## The headline menu row was mis-filed

A-11/RM-44 + A-22/RM-91 + A-21/RM-90 S3 had each independently named
"champion-sensitivity in `ds.ehp`" as their blocker and successor. **That
shipped at 1.247.0.** Three rows agreeing was not evidence - all three had
inherited the same unverified premise.

The real cause is two constants. `ehp.py:1212-1218` arms
`assume_item_crit_dr` / `assume_item_aa_dr` / `assume_item_enemy_as_slow` off
`_ASSUMED_INCOMING_CRIT_SHARE = 0.5` and `_ASSUMED_INCOMING_AA_SHARE = 0.5`,
and no route or client could disable them. They are worth **+49.7 pct to
Randuin's** (2419.95 -> 1616.30 forced off) and flip it **#1 -> #6**. In the
shipped SR table 28 champions share one byte-identical `mixed` order led by
Randuin's; the `poke` profile, which targets a squishier dummy, drops it to slot
6 - the tell. Now exposed through all three gates, byte-identical by default.

All three candidate "lift" shapes were rejected ON MEASUREMENT, not taste. See
LEDGER 1050.

## What else shipped

- **3 champions shipped `weighted_dps == 0.0` silently.** `dps.py` gated its
  degenerate fallback on all-phase instead of the selected phase. Azir/Karthus/
  Viktor now report real values; 170 of 173 byte-identical. **This is the actual
  cause of the four-session A-13/RM-48 "Azir soldier axis" misdiagnosis** -
  `onhit_dps.py:162` sums ability+auto, so a 0.0 made `/rank-onhit` return a
  `/rank-mage`-identical response with `notes == []`.
- **Locke and Zaahen had NO ability data at all** (roster 173, keyspace 171).
  New hand-authored registry, injected keys-not-present-only, DEFAULT-ON. Burst
  0.0 -> 418.61 / 959.79, 171 of 171 others byte-identical. **Locke's shipped SR
  build went from a marksman template to a correct AP mage build.** Zaahen's
  correctly did not move - his damage really is physical.

## Four rows closed without code

A-13/RM-48 Azir (BLOCKED-UNFALSIFIABLE - nine mages, pet or no pet, identical
ordering), A-32/R190 kit-pen (3 of 4 mis-filed; the row even names the wrong
module), A-17/RM-85 Nasus (MIS-FILED - five routes return the IDENTICAL 135-item
set; "absent from top-40" was the `top=40` trap), and the RM-44/RM-91/RM-90 S3
convergence above. A-17/RM-83 Naafiri is SHIPPED-ALREADY but gate-blocked;
A-17/RM-96 Zilean is REAL and specced but not built.

## Corrections to my own work this session

- My first seam census said **36** stranded. It used substring matching, so
  `gate_caster_hp` / `gate_target_hp` were phantoms of their `_amp` siblings.
  Word-boundary count is **34**. A build agent caught it and was right to trust
  its own measurement over my brief.
- My build brief gave a build agent **two wrong wiki numbers** (Grim Deliverance
  50 pct vs the real 200 pct bonus AD; `Ritual Nails` attributed to Zaahen when
  it is Locke's Q). The agent re-fetched, corrected both, and I re-verified via
  the wiki API. **Telling agents to trust their own measurement over the brief
  is what saved this.**
- I warned only ONE of three build agents about the `_HOST_DEPENDENT_TESTS`
  mirror trap. The two tests that needed it were written by a different agent
  and broke the RC suite. Registered by name.

## Fences added

- **Row agreement is not evidence.** Three rows converging on one prerequisite
  meant three rows inheriting one unverified premise. Verify the prerequisite
  before treating convergence as strength.
- **A pinned "signature tail" assertion is self-defeating** under an
  append-at-END convention. Three tests carried one; each fails on the next
  legitimate append - the very convention they exist to protect. Repair the
  premise onto the shipped path (case the entry points separately), never
  weaken the assertion.
- **`/rank*` returns `item_id` as a STRING.** A probe comparing against integer
  ids reads ABSENT for every watched item and looks exactly like a clean
  pool-exclusion finding. Same status as the `top=40` and empty-list traps.

## Still open off this session

- **RM-115 priority list** (in value order): plumb `apply_ability_base_overrides`
  through gates 2+3; `apply_passive_aura_damage` gate 3; `kit_conversion_strength`
  on `/rank-assassin` + client (closes RM-83, already seeded and green in-engine);
  give `hybrid.py` the kwarg at all (unblocks Olaf/Pantheon/RekSai/Riven).
- **RM-96 Zilean** is fully specced. Trap for whoever builds it: his `ability_hps`
  MAGNITUDE is 4.66 vs Janna 5.06, only 8 pct apart - a factor seeded off HPS
  magnitude produces a silent null. Only the CAST RATE separates him (0.00424,
  15.9x below Soraka).
- **`parse_leveling_bases` blind spot** (`ds_wiki_staleness_check.py:188-196`):
  keeps only the first label pair per `{{st}}` block; 31 of 90 blocks in a
  50-page sample carry two or more, dropping 35 Meraki-matching labels. So
  `ability_staleness.json` is a structural undercount and
  `_ability_base_overrides`'s "exactly those six" scope derives from it.
- **B1 shipped code with no data** - `--full-roster` exists but no 16.14.1
  artifact was regenerated with it.
- **DS `:8893` restart quirk, RESOLVED but worth knowing.** The first
  `Stop-ScheduledTask` / `Start-ScheduledTask` of `RC-DaemonSlayer` left state
  `Ready` with `LastResult 0x0` and nothing listening, twice. The code was never
  the problem - the same entry point served 1.250.0 immediately when launched in
  the foreground. Recovered by `taskkill /F` on the foreground PID and starting
  the task again; it is now **Running** and `/health` reads 1.250.0. Root cause
  of the initial no-start is NOT established. If it recurs, check for a listener
  already holding `:8893` before assuming a code fault. Note `taskkill /F` must
  be run from PowerShell - Git Bash mangles `/F` into a path.

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
