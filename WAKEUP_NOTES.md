# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25i - RM-115 priority 4: the bruiser gate, and Option B paid for itself (ENGINE 1.252.0)

ENGINE **1.251.0 -> 1.252.0**, patch 16.14.1. Operator-directed single slice
("go with option B and build priority 4"), main thread. Tier-2 in ritual order:
bump by quoted literal (132 files / 153 occurrences) -> :8893 restarted ->
`/health` re-read **1.252.0 BEFORE the regen** -> both build-order families
across both keyspaces -> Share sync (492 files, `--check` green) -> all four
ENGINE doc sites.

Suites, both measured fresh AFTER the last edit:
**DS 9702 passed / 1 skipped / 4650 subtests.**
**RC `tests/` 13110 passed / 106 skipped / 460 subtests.**

## All four filed RM-115 priorities are now shipped

`hybrid.py` had ZERO occurrences of `kit_conversion_strength`, stranding Olaf /
Pantheon / RekSai / Riven at GATE 1. All three gates shipped in one slice,
because gate 1 alone is exactly the RM-115 failure mode - a seam measurable only
from a test file. `rank_items_by_hybrid` is the only target: it is the sole
entry point in the module that SORTS, and the RM-86 transform is a sort-key
transform, so `compute_hybrid` would have carried a kwarg that looks like a
capability and does nothing.

| champion | BotRK | Kraken | Guinsoo's | head |
|---|---|---|---|---|
| Olaf | **#1 -> #20** | #3 -> #58 | #8 -> #60 | Trinity **#2 -> #1** |
| Riven | #1 -> #4 | #5 -> #44 | #18 -> #50 | Trinity #2 -> #1 |
| RekSai | #1 -> #9 | #3 -> #51 | #11 -> #57 | Trinity #2 -> #1 |
| Pantheon | #1 -> #61 | #13 -> #84 | #34 -> #94 | Trinity #2 -> #1 |
| **Darius (control)** | #1 -> #1 | #5 -> #5 | #17 -> #17 | **byte-identical** |

Measured live through `rank_bruiser_for` with the BEFORE payload captured before
any edit and asserted unchanged. The dispatcher moves too (Olaf bruiser top-1
3153 -> 3078), which is what makes it reachable from a coach tick. All nine
build tables byte-identical.

## Option B was not the cautious choice - it was the correct one

The filed concern was that the bare damage axis would "over-fire" for Naafiri
and Orianna. It is worse: at strength 1.0 the bare axis multiplies Warmog's,
Randuin's, Thornmail, Dead Man's Plate and Sterak's Gage by **EXACTLY 0.0** for
both - total suppression of every tank item on a scorer whose beta term IS
effective HP, on a route that accepts any champion. Silent, no symptom test.

The blended sets are the INTERSECTION of the damage set and the `ehp` set, and
are machine-checked against that derivation rather than hand-listed:
`hybrid_ad = {FlatMagicDamageMod}`, `hybrid_ap = {FlatPhysicalDamageMod,
PercentLifeStealMod}`. `test_hybrid_objective_protects_ehp_stats` asserts BOTH
sides - that the bare axis annihilates and the blended one does not - so the
cheaper option cannot be quietly substituted later.

## The pinned-tail hazard fired, and was repaired not suppressed

Appending the kwarg at END broke `test_rune_resist_signature_convention_r134.py`
GUARD 1 - the self-defeating pinned-tail shape fenced last session. Its own
docstring names the correct response ("the intended forcing function"), so the
two HYBRID entry points were cased separately, exactly as the two EHP ones were
at 1.250.0, and the assertion stayed at full strength.

**A new assertion added in the same edit caught an error in my own first
draft.** I asserted the gate was absent from every non-hybrid entry point;
`rank_items_by_ehp` has carried it since RM-86. The real invariant is cleaner
and is what shipped: **both RANKERS carry it, neither `compute_*` does**, with
the ABSENCE half load-bearing.

## Corrections

- Pantheon and RekSai read #59 and #8 in-process but **#61 and #9 live** - the
  route carries `enemy_ad_share` / `enemy_ap_share` that the in-process call did
  not. The live figures are the ones published.

## Still open off this session

- **The other 98 per-route stranded pairs** are now the whole of RM-115.
  `/ehp`, `/hybrid`, `/rank-tank` and `/rank-bruiser` share ONE 18-19 seam
  EHP-family block, so a single client wiring pass would likely clear most of
  them. **Do NOT do all of them in one session** - each needs its own
  before/after with a named control. `/beam` and `/v2/fight-report` have no
  client function at all.
- **`kit_conversion_strength` is not seam-PREFIXED**, so it appears in NEITHER
  reachability ledger. That is why this slice carries its own acceptance test,
  and it is worth remembering before trusting either guard's green for a
  non-prefixed seam.
- **RM-96 Zilean**, **`parse_leveling_bases`** (35 labels dropped across 31 of
  90 blocks), **B1**'s unregenerated `--full-roster` artifact, and the
  `rank_assassin_for(assume_magic_burst=...)` dead parameter all carry forward
  unchanged.

---

# 2026-07-25h - RM-115 first drain pass: three seams wired, and the count was wrong (ENGINE 1.251.0)

ENGINE **1.250.0 -> 1.251.0**, patch 16.14.1. Four read-only probe agents in
parallel on the four RM-115 priority plumbs, then the wiring applied in the
MAIN THREAD - all three shipped slices edit the same two files
(`agents/daemon_slayer/server.py`, `core/daemon_slayer_client.py`), so worktree
agents would have been false parallelism, not speed. Tier-2 in ritual order:
bump by quoted literal (132 files / 153 occurrences, `.claude` +
`docs/_archive` + `Share` excluded) -> :8893 restarted -> `/health` re-read
**1.251.0 BEFORE the regen** -> both build-order families across both keyspaces
-> Share sync (491 files, `--check` green) -> all four ENGINE doc sites.

Suites, both measured fresh AFTER the last edit:
**DS 9692 passed / 1 skipped / 4646 subtests.** RC `tests/` 13110 passed / 106 skipped / 460 subtests.

## The result that matters: the debt is 3x bigger than filed

RM-115 shipped last session with a headline of **34 stranded seams**. That
number answers the weaker of two questions. `test_route_seams_reach_the_client.py`
collapses reachability to a NAME - "is this seam settable from the client AT
ALL" - so `apply_mode_modifiers`, parsed by SEVEN routes, reads as reached on
all seven the moment ONE client function names it, and
`apply_item_resist_grants` on `/ehp` hides behind its `/rank-tank` wire.

Measured per **(route, seam)** pair the stranded set is **101**, concentrated in
`/rank-bruiser` 20, `/hybrid` 19, `/rank-tank` 19, `/ehp` 18, plus `/beam` and
`/v2/fight-report` which have NO client function at all.

The sharpest proof that the name-based guard is insufficient: **it stayed GREEN
the entire time `/rank-assassin` could not set `kit_conversion_strength`**,
because `rank_for` already named it on the carry path. New
`test_route_seams_reach_the_client_per_route.py` carries the stronger question
with the same self-cleaning equality contract. **Do not treat the name-based
guard's green as evidence that a specific route is wired.**

## What shipped (each with a live before/after and a NAMED control)

| seam | gates fixed | headline | control |
|---|---|---|---|
| `apply_ability_base_overrides` | 2 + 3 (was 0/0/0) | Morde `/rank-mage` rank-2 swap; Naafiri rank-3 swap | Ziggs, Lux, Zed, Talon byte-identical |
| `apply_passive_aura_damage` | 3 (+ an unfiled `/ability-dps` gate-2 half) | Void Staff 69.059 -> 208.800, top-1 REORDERS | Ahri byte-identical |
| `kit_conversion_strength` on `/rank-assassin` | 2 + 3 | Naafiri BotRK **#2 -> #23** (core-3) | Talon, Zed byte-identical over all 60 rows |

All DEFAULT-OFF. **All nine shipped build-table files across both keyspaces are
byte-identical after stamp-stripping** - the artifact proves the default.

`apply_ability_base_overrides` turned out to be a **ROUTE-LEVEL-ONLY** plumb:
every engine intermediate already carried `abilities_snapshot`. But the flag is
LOAD-time and `abilities.load_default()` is keyless, so `server.py` gained
`_AbilitiesOverrideCache` - builds the flag-ON snapshot once (~30 ms),
`get(False)` returns `None` so the OFF path is untouched. It is reset in
`start_server` so it cannot outlive its `DataSnapshot`.

## Corrections made this session

- **A probe's "bonus defect" was wrong in its fix direction and I did not apply
  it.** The client emits `assume_magic_burst` to `/rank-assassin` while only
  `_route_burst` parses it; the probe filed that as a missing route parse.
  `server.py:1971-1973` documents deliberately that `rank_items_by_burst` does
  NOT accept it and only `compute_burst_damage` does - so the ROUTE is correct
  and the real defect is the CLIENT exposing a parameter that can never take
  effect. Filed, not fixed; the fix direction is a genuine choice.
- **My brief's `11.677 -> 72.155` headline did not reproduce** at the probe's
  params (it measured `11.700 -> 48.904`). Parameterization, not contradiction -
  but third session running where reproducing a finding's ORIGINAL params was
  the difference between a correction and a false retraction.

## Still open off this session

- **RM-115 priority 4 is SPECCED and deliberately NOT BUILT.** `hybrid.py` has
  ZERO occurrences of `kit_conversion_strength`, stranding Olaf / Pantheon /
  RekSai / Riven at GATE 1. `rank_items_by_hybrid` (`hybrid.py:969`) is the only
  target - `compute_hybrid` has no sort key so the kwarg is inert there. It is
  held on a REAL decision, not budget: **the objective string.** Passing the
  local `axis` is the minimal diff and is measured INERT for all four named
  champions (`off_axis_stat` 1.00 -> shortfall exactly 0), but OVER-FIRES for
  Naafiri and Orianna (`off_axis_stat` 0.00) on a scorer whose beta term IS
  EHP. Alternative: a `hybrid_{axis}` off-axis set in `kit_conversion.py`
  (+6 lines, the intersection of the damage and EHP sets), which reproduces
  Olaf's own registry note verbatim. Gates 2+3 are ~7 further lines.
- **The other 98 per-route stranded pairs.** `/ehp`, `/hybrid`, `/rank-tank` and
  `/rank-bruiser` share one 18-19 seam EHP-family block - one client wiring pass
  would likely clear most of it. Do NOT do all of them in one session; each
  needs its own before/after with a named control.
- **RM-96 Zilean** still fully specced, still unbuilt. Trap: a factor seeded off
  `ability_hps` MAGNITUDE gives a silent null (4.66 vs Janna 5.06); only the
  CAST RATE 0.00424 separates him.
- **`parse_leveling_bases`** dropping 35 labels across 31 of 90 blocks, and
  **B1**'s `--full-roster` artifact that was never regenerated.

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
