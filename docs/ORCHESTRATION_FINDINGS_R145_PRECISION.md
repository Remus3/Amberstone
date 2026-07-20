# R145 Slice B - Precision-tree offensive rune audit

**Status:** AUDIT-ONLY. No engine code changed, no `ENGINE_VERSION` bump, no new
registry module. Slice A owns the single permitted build and the version bump.

**Date:** 2026-07-20
**Engine at audit time:** 1.231.0 (patch 16.14.1)
**Ground truth:** `data/meta_build/ddragon/16.14.1/runesReforged.json`
(DDragon only - never aggregator D / aggregator A). Every magnitude below is quoted
VERBATIM from the `longDesc` field.
**Machine guard:** `tests/test_rune_precision_offense_audit_r145.py`
(16 tests / 24 subtests, mutation-checked).

---

## 0. The structural finding (read this first)

`agents/daemon_slayer/rank.py` and `agents/daemon_slayer/ability_dps.py` contain
**ZERO occurrences of the substring "rune"** - verified by
`grep -c rune` returning `0` for both files. There is no rune surface on the
item-ranking scorer or the sustained-ability-DPS scorer at all.

`agents/daemon_slayer/hybrid.py` accepts a `rune_ids` transport
(`hybrid.py:429`, `hybrid.py:947`) but every flag riding it is DEFENSIVE and
routes to `compute_ehp`: `apply_rune_resist_grants` (`hybrid.py:428`),
`apply_rune_health_grants` (`hybrid.py:432`), `apply_rune_hsp_amp`
(`hybrid.py:433`), `apply_rune_flat_mitigation` (`hybrid.py:437`),
`apply_rune_self_heal` (`hybrid.py:442`), `apply_rune_shield_grants`
(`hybrid.py:443`). That is the R132 / R136 / R142 defensive half, already closed.

The ONLY offensive rune consumer in the engine is `agents/daemon_slayer/burst.py`
(imports at `burst.py:118-120`, consumption at `burst.py:1029-1071`), and it
only fires when a caller passes an explicit `runes=` sequence to
`compute_burst_damage`. `burst.py:1022-1023` records that "the live default
passes no runes so /rank is unaffected."

**Consequence:** every "CREDITED" verdict below is credited in the burst window
ONLY, on an opt-in argument. No Precision rune influences item ranking.

---

## 1. Per-rune table

All 13 Precision runes verified present in the 16.14.1 feed (ids confirmed
against the feed, not against the brief - the brief omitted 9101 Absorb Life).

| id | name | verdict | site / feed evidence |
|---|---|---|---|
| 8005 | Press the Attack | CREDITED (burst) | `rune_procs.py:550-565` `stacking_amp`, `_PTA_AMP_MULT = 1.08` at `rune_procs.py:451`; burst piece `_press_the_attack_burst` `rune_procs.py:200`. Feed: "deals 40 - 160 bonus adaptive damage (based on level) and amplifies your damage dealt by 8%" |
| 8008 | Lethal Tempo | CREDITED (damage half) / UNCREDITED-REAL-GAP (AS half) | `rune_procs.py:699-717` `per_attack`, `_lethal_tempo` at `rune_procs.py:270`. The on-attack damage is credited; the ATTACK SPEED grant is not - `bonus_as` is only ever an INPUT to the closure, never an output onto an attack-speed axis. Feed: "grants you [6% Melee \|\| 4% Ranged] Attack Speed for 6 seconds, up to 6" = 36% melee / 24% ranged at cap, unmodelled |
| 8021 | Fleet Footwork | OUT-OF-OFFENSIVE-AXIS (documented honest exclusion) | `rune_procs.py:387-394`. Feed: "Energized attacks heal you for 10 - 130 (+0.1 Bonus AD, +0.05 AP) and grant 20% Move Speed for 1s." Heal + MS, no damage component. The heal side is an EHP-numerator question, not an offensive one |
| 8010 | Conqueror | **UNCREDITED-REAL-GAP** | Registered `rune_procs.py:566-581` with `proc_type="adaptive"`; `burst.py:1034` reads `if proc is None or proc.proc_type == "adaptive": continue`. `keystone_amp` is a documented no-op for it (`rune_procs.py:899-902`). Feed: "gaining 1.8-4 Adaptive Force per stack. Stacks up to 12 times." = 21.6 to 48 adaptive force at cap. Should feed the AD/AP stat axis |
| 9101 | Absorb Life | **DATA-BLOCKED** | Absent from every DS module (grep: 0 hits). Feed longDesc verbatim: "Killing a target heals you for @HealAmount@." Unresolved placeholder - no magnitude derivable, do not guess |
| 9111 | Triumph | OUT-OF-OFFENSIVE-AXIS | Absent from every DS module. Feed: "Takedowns restore 5% of your missing health, 2.5% of your max health, and grant an additional 20 gold." Heal + gold, no damage axis |
| 8009 | Presence of Mind | OUT-OF-OFFENSIVE-AXIS (resource) | Absent. Feed: "Damaging an enemy champion restores 6-50 (80% for ranged) mana or 6 energy." Resource axis. DS has a mana substrate but no rune feed into it |
| 9104 | Legend: Alacrity | **UNCREDITED-REAL-GAP** | Absent from every DS module. Feed: "Gain 3% attack speed plus an additional 1.5% for every Legend stack (max 10 stacks)." = flat 18% attack speed at cap. Should feed the attack-speed axis in `compute_dps` |
| 9105 | Legend: Haste | UNCREDITED - do not build | Absent. Feed: "Gain 1.5 basic ability haste for every Legend stack (max 10 stacks)." = 15 basic ability haste. **Ability Haste as a DS axis was MEASURED INERT and answered NO** (memory `project_ds_ability_haste_measured_inert`). Not a gap; a settled negative |
| 9103 | Legend: Bloodline | OUT-OF-OFFENSIVE-AXIS (sustain + EHP) | Absent. Feed: "Gain 0.45% Life Steal for every Legend stack (max 15 stacks). At maximum Legend stacks, gain 85 max health." = 6.75% life steal + 85 HP. Life steal is sustain, the 85 HP is EHP-numerator - both belong to the closed defensive half |
| 8014 | Coup de Grace | CREDITED (burst) | `rune_procs.py:643-664`, `_COUP_DE_GRACE_AMP_MULT = 1.08` at `rune_procs.py:460`. Feed: "Deal 8% more damage to champions who have less than 40% health." Applied unconditionally by default; honest gate behind `gate_target_hp_amp` (R51 seam, `burst.py:584-591`, DEFAULT-OFF) |
| 8017 | Cut Down | CREDITED (burst) | `rune_procs.py:665-683`, `_CUT_DOWN_AMP_MULT = 1.08` at `rune_procs.py:461`. Feed: "Deal 8% more damage to champions who have more than 60% health." Same R51 gate seam |
| 8299 | Last Stand | CREDITED (conditional, no-op by default) | `rune_procs.py:722-741`, ramp `_last_stand_amp` at `rune_procs.py:298`, consumed `rune_procs.py:956-963`. Feed: "Deal 5% - 11% increased damage to champions while you are below 60% health. Max damage gained at 30% health." At the default `caster_hp_pct=1.0` the amp is exactly 1.0, so it contributes nothing to a default burst - by design (R53 seam `burst.py:593-600`, DEFAULT-OFF) |

### Measured behaviour (this run)

`compute_burst_damage(Darius, level 11, items [3031, 3072], SR, target 80 armor /
60 MR / 2000 HP / 600 bonus HP)`:

```
base (no runes)      1473.1788194444443
runes=[8005]         1701.6213602941175   credited
runes=[8014]         1591.033125          credited
runes=[8017]         1591.033125          credited
runes=[8008]         1494.5317606209148   credited
runes=[8010]         1473.1788194444443   IDENTICAL -> uncredited
runes=[8299]         1473.1788194444443   IDENTICAL -> no-op at full HP (by design)
runes=[9104]         1473.1788194444443   IDENTICAL -> uncredited
runes=[9103/9111/8009/8021/9101/9105]     IDENTICAL -> uncredited
compute_rune_proc_damage(8010, 11) = 3.0941176470588236   (per-stack, computed but never consumed)
```

The Conqueror line is the sharpest evidence in this audit: the per-stack value
IS computed correctly and returns a positive number, and the burst total still
does not move by a single float ULP.

---

## 2. Ranked recommendation (recommendation ONLY - not a build)

### #1 - Conqueror 8010: consume the existing adaptive-force closure

Highest value, and it is the cheapest of the candidates because **the data work
is already done**. `_conqueror_adaptive` (`rune_procs.py:208`) already returns
the feed-exact 1.8-4.0 per-stack ramp; the only missing piece is a consumer.
Reasons it ranks first:

1. **Magnitude.** 12 stacks x 1.8-4.0 = 21.6 to 48 adaptive force. At level 11
   that is ~37 adaptive force - comparable to a full component item, on the
   exact AD/AP axis the scorers already model natively.
2. **Zero new data risk.** No constant would be invented; the closure is already
   feed-sourced and test-covered. This is a consumer seam, not a registry build.
3. **Population.** Conqueror is the default keystone across the fighter/bruiser
   and many melee-carry cohorts - the cohort DS's bruiser and carry scorers
   serve most often.
4. **It is a stat, not an event.** Unlike a proc, adaptive force composes cleanly
   with the existing stat resolution, so it does not risk the double-count class
   of bug that burned the DSV1 burn-proc fold.

Suggested shape for whoever builds it (NOT built here): a DEFAULT-OFF flag in
the usual convention (`apply_rune_adaptive_force` + the existing `rune_ids`
transport) that folds the per-stack force into resolved AD/AP, with an explicit
stack-count parameter defaulting to 0 so the no-flag path stays byte-identical.
Note the guard test asserts `"rune" not in rank.py` - wiring it there is exactly
the deliberate acknowledgement the guard is designed to force.

### #2 - Legend: Alacrity 9104 attack speed

Flat 18% attack speed at cap, feed-exact, straight onto an axis `compute_dps`
already owns. Ranks second only because it needs a net-new registry entry rather
than a consumer for an existing closure, and because its stack count is a
game-state quantity (takedowns/minions) the engine has no headless signal for -
so it would need an assumed-stacks parameter, which is a modelling choice
somebody has to make rather than read off the feed.

### #3 - Lethal Tempo 8008 attack-speed half

Same axis as #2 and the rune is already registered, but the AS half is
self-referential (its own on-attack damage scales by bonus AS), so crediting it
needs care to avoid feeding the rune's AS back into its own damage term twice.
Lower value, higher bug surface.

### Explicitly NOT recommended

- **Legend: Haste 9105** - ability haste was MEASURED INERT as a DS axis. Settled
  negative, do not re-pitch.
- **Absorb Life 9101** - DATA-BLOCKED at the feed (`@HealAmount@`). Nothing to
  build without inventing a constant.
- **Fleet Footwork 8021 / Triumph 9111 / Legend: Bloodline 9103** - the value is
  heal / sustain / max-HP, i.e. the defensive half closed by R132 / R136 / R142.
  Out of this slice's axis; re-open there if at all.

---

## 3. Verification performed

- `py_compile tests/test_rune_precision_offense_audit_r145.py` - OK
- `pytest tests/test_rune_precision_offense_audit_r145.py -q` - 16 passed,
  24 subtests passed
- Mutation check: perturbing 5 assertion inputs (moving 8010 + 9104 into the
  credited set, moving 8005 into the uncredited set, changing the PtA amp
  expectation to 1234.0, changing the `@HealAmount@` sentinel, and relaxing the
  rank.py/ability_dps.py substring) produced **8 failed, 14 passed** - the guard
  is non-vacuous. Reverted; re-run confirms 16 passed / 24 subtests.
- `ruff check .` - clean
- `pytest agents/daemon_slayer/tests/ -q` - see the slice report for the count;
  no engine code was changed in this slice.
