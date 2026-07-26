# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25j - the EHP-family block drained, and the transports nobody was counting (ENGINE 1.253.0)

ENGINE **1.252.0 -> 1.253.0**, patch 16.14.1. Operator-directed ("drain the
EHP-family block next"). Four read-only probe agents in parallel gathered
acceptance evidence for all 20 seams against live :8893; the wiring itself is
ONE file, so it was applied in the main thread. Tier-2 in ritual order: bump by
quoted literal (132 files / 153 occurrences) -> :8893 restarted -> `/health`
re-read **1.253.0 BEFORE the regen** -> both build-order families across both
keyspaces -> Share sync (492 files, `--check` green) -> all four ENGINE doc
sites.

Suites, both measured fresh AFTER the last edit:
**DS 9721 passed / 1 skipped / 4653 subtests.**
**RC `tests/` 13110 passed / 106 skipped / 460 subtests.**

## The headline

**Per-route stranded debt 101 -> 25. Name-collapsed 33 -> 12.** Twenty seams
shared by `/ehp`, `/hybrid`, `/rank-tank` and `/rank-bruiser` (17 on all four)
were engine- and route-complete but unreachable from the client: 76 of the 101
pairs.

Evidence standard, stated because it narrows the operator's one-control-per-seam
rule deliberately: REACHABILITY proven structurally for all 76 pairs by the
per-route guard (that is what it exists for); behavioural EFFECT proven ONCE per
seam on its most diagnostic route against a NAMED registry-proven control. 19
live cases through the real client.

## Two findings that outlive this block

**THREE STRANDED TRANSPORTS, and BOTH guards are blind to all three** because
none is seam-PREFIXED. `rune_ids` and `enemies` were parsed by all four routes
and sent by NO client function; `score_by` was missing from `rank_bruiser_for`.
EIGHT of the twenty seams consume one of them, so wiring the flags alone would
have made ~16 pairs reachable-and-DEAD - the exact illusion RM-115 exists to
kill, introduced by the fix for it. It surfaced only because the acceptance test
was written from MEASURED cases and failed with `TypeError: unexpected keyword
argument 'enemies'`. A test built from assumptions would have gone green.
**Any future drain must check the non-prefixed transports a seam consumes.**

**A defect I introduced and caught before shipping.** `apply_build_tenacity` is
TRI-STATE - `_route_rank_tank` (`server.py:701-703`) and `_route_rank_bruiser`
(`:973-975`) read it as None-when-absent and the engine defaults it ON under
`score_by="cc_blended"`. My first pass gave it the uniform `bool = False` +
emit-when-True treatment of the other nineteen, which cannot express False: an
OFF switch that could not turn anything off. Now `Optional[bool] = None`, with
an assertion that omitting the key reproduces the ON ordering. Confirmed it is
the ONLY tri-state seam by an AST scan of all four handlers, not by eye.

## Recorded so nobody rediscovers them

- **Three seams provably CANNOT reorder**: `apply_survival_window`,
  `apply_passive_revive`, and `apply_champion_tenacity` without
  `apply_build_tenacity`. Each is a uniform multiplier on the EHP numerator and
  a ratio sort key is invariant under uniform scale - Tryndamere's ratio is
  exactly 1.291666667 on all 138 rows, both sort keys. The "moved" rows for
  Zac/Anivia/K'Sante are 1e-12 ULP ties. Acceptance is the `/ehp` SCALAR; a rank
  criterion is unsatisfiable by construction.
- **`apply_mode_modifiers` is INERT on ARAM.** The ARAM axes apply
  unconditionally; the flag gates the wiki-sidecar lane, which excludes ARAM to
  avoid double-counting. URF is the mover. An ARAM case would look like a bug.
- **Seven companion gates**, each a false negative if missed - rune ids, a
  SHIELD for `apply_rune_hsp_amp`, level >= 7 for `assume_item_health_stacks`,
  `enemies` AND an unsaturated comp for the spell shields (five heavy-CC enemies
  pin `cc_pressure_fraction` at 1.0 and the clamp eats the seam), build tenacity
  for champion tenacity, and `target_max_hp` (NOT `target_hp`) for the AD axis.
- **One control shape is INVALID and the test asserts it**: a manaless champion
  is not a control for `apply_item_mana_health` - the item supplies its own mana
  (Garen 5099.337 -> 5242.948).

## Corrections to my own work

- I said `apply_mode_modifiers` is parsed by **SEVEN** routes, three times. It
  is **EIGHT**. Corrected in the live artifacts; LEDGER 1051 and the
  1.250.0/1.251.0 CHANGELOG entries are append-only and were left as written,
  with the correction recorded forward.
- The guard assertion pinning the per-route ledger at a FLOOR of 33 was
  disproved by this drain (25 vs the sibling's 12). The premise was wrong, not
  the number, so it was replaced with the inequality that holds BY
  CONSTRUCTION: a name stranded everywhere contributes at least one (route,
  seam) pair, so per-route total >= name-collapsed total, always.

## Still open

**25 pairs, and none is a shared block:** `/burst` 7, `/dps` 6,
`/rank-assassin` 4, `/v2/fight-report` 3, `/rank` 2, one each on
`/ability-dps`, `/rank-mage`, `/beam`. **`/beam` and `/v2/fight-report` have NO
client function at all** - those four pairs need one invented before any wiring.
The cheap shared-block phase of RM-115 is over; what remains is per-seam work.

Unchanged carry-forwards: RM-96 Zilean, `parse_leveling_bases` (35 labels across
31 of 90 blocks), B1's unregenerated `--full-roster` artifact, and the
`rank_assassin_for(assume_magic_burst=...)` dead parameter.

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
