# SCOPE VERDICT - RM-92 ability-haste slice

Session 2026-07-18. Read-only sizing pass. Nothing built, nothing bumped.
Live DS probed BEFORE any claim: `GET :8893/health` -> `engine_version 1.220.0`,
`patch 16.14.1`, `champions 173`, `items 706`.

## VERDICT: DEFER. This is not a registry hookup.

It is MODEL work of the RM-86 / RM-39 class, and it is **already spec'd twice**
(RM-39 Aatrox, RM-43 Ambessa - both say "credit ABILITY HASTE in the hybrid DPS
term", RM-39 tagged "anchor of the largest family in the sweep"). The RM-92
ability-haste slice is not a new work item; it is the same work seen from the
item side instead of the champion side. Do not open a third id for it.

A finding the hand-off did not anticipate makes the case stronger than "defer
because it is expensive": **the ability-haste term is ~1% live even in the one
scorer that already prices it.** Building AH into `dps` / `hybrid` would be
extending a branch that is measurably almost never taken.

## 1. None of the 5 champions can reach the AH-pricing scorer

Route decided at `core/archetype_picks.py:447` (`default_for_champion`),
dispatched at `core/daemon_slayer_client.py:1350` (`rank_for_primary_archetype`).
`ability_dps.py` is reachable ONLY via `arch == "mage"`
(`core/daemon_slayer_client.py:1544` -> `"scorer": "ability"` at `:1567`).

| champion | tags | archetype | scorer | prices AH? |
|---|---|---|---|---|
| Twitch | Marksman, Assassin | carry | `dps.py` | no |
| Xayah | Marksman | carry | `dps.py` | no |
| Yunara | Marksman | carry | `dps.py` | no |
| Udyr | Fighter, Tank | bruiser | `hybrid.py` | no (AD branch) |
| Yorick | Fighter, Tank | bruiser | `hybrid.py` | no (AD branch) |

All five take the identical plain-tag path and exit at
`core/archetype_picks.py:498`. None appears in any override roster: Slice A
`core/archetype_picks.py:160-162`, Slice B `core/ds_onhit_ap_roster.json`,
Slice C `core/ds_support_route_overrides.json`. Every override slice is a no-op
for them. Zero of the five reach `ability_dps.py`.

## 2. `dps.py` has no surface an AH term could attach to

Not "no AH term" - no ability model at all. Stated in the module docstring at
`agents/daemon_slayer/dps.py:34-37`: ability damage is not included, spell
formulas are not in the snapshot. Confirmed by imports (`dps.py:40-69`): no
`abilities` import. Grep for a cooldown token in `dps.py` returns zero matches
outside comments about item internal cooldowns.

The scoring core `_rotation_attack_dps` (`dps.py:508-581`) sums basic-attack
terms only: `dps.py:561-562`. The two proc cadences are `every_n_attacks`
(`dps.py:305`, scales with attack speed) and `every_n_seconds` (`dps.py:325-326`,
a fixed item internal CD). Neither is ability-haste-affected in game.

There is exactly one per-second cast quantity in the file: `ult_casts_per_sec`
(`dps.py:1023`). It is **not** cooldown-derived - `get_ult_casts_per_sec`
(`ult_rates.py:83-108`) returns a measured median from `ult_cast_rates.json`,
sampled from `rewind_history.db spell4_casts`. Multiplying an empirical rate by
a haste factor double-counts whatever haste the sampled players already had.
It is a haste-hostile hook, not a free one.

## 3. `hybrid.py` AD branch inherits exactly that hole

`hybrid.py` computes no damage of its own; its score line is
`hybrid_score = alpha * dps_for_score + beta * ehp_for_score` (`hybrid.py:488`).
The damage term branches on kit axis at `hybrid.py:462-468`:

- AP champions -> `_ability_damage(...)` -> `compute_ability_dps(...)`
  (`hybrid.py:43` module-level import, called `hybrid.py:463`). **These already
  get ability haste for free, no new code.**
- AD champions -> `dps_result.weighted_dps` (`hybrid.py:468`), i.e. section 2's
  model verbatim, with the same hole.

Udyr and Yorick are AD-axis bruisers, so both take `hybrid.py:468` and get
nothing - despite both being heavily ability-rotation-driven kits. That is the
RM-92 instance, and it is a MODEL gap, not a wiring gap.

## 4. DECISIVE, and new: AH is ~1% live where it IS wired

`ability_dps.py` derives haste unconditionally (`:1097-1098`) and computes the
Riot-canonical effective cooldown (`:1161-1164` -> `:542` ->
`_item_ability_haste.py:285-309`, `base_cd / (1 + haste/100)` at `:306`+`:309`).

But the shortened cooldown is consumed ONLY inside the measured-rate-miss
fallback at `ability_dps.py:1231-1234`:

```
measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)   # :1228
if measured <= 0:                                                        # :1231
    theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0              # :1232
    ...
dps = post_mit * measured                                                # :1237
```

When `measured > 0` the cooldown is written to the dataclass at `:1252` and
never multiplied into anything - pure reporting.

**Measured against the live table** `data/daemon_slayer/spell_cast_rates.json`
(172 champion entries, 680 SR champion-spell pairs):

- **8 of 680 SR pairs (1.2%) have `measured <= 0`** and can reach the AH branch:
  Aphelios E, Katarina E, Kled W, Teemo E, TwistedFate E, Vayne W, Vi W,
  XinZhao E.
- 2 of those 8 are unreachable anyway. `ability_dps.py` looks up by DISPLAY name
  (`engine.py:461` sets `champion_name=champ.get("name", ...)`) while the rates
  file is keyed by DDragon id, so TwistedFate and XinZhao silently miss and take
  the non-zero `global_fallback` instead. **21 champions** have `id != name` and
  are present in the rates file, all silently taking the fallback.
- Effective live surface: **6 champion-spell pairs, ~0.9%.**

So the "already wired" scorer prices ability haste into a score for six spells
in the whole game. Wiring an AH term into `dps` / `hybrid` would feed the same
architecture.

## 5. Data quality on the one live path is poor

- `data/daemon_slayer/16.14.1/champion_abilities.json` carries **171** champions
  vs **173** in `champions.json`. Locke and Zaahen are absent and return
  `_empty_result` (`ability_dps.py:1106-1118`). This is the known RM-79 shape.
- 11 champions have a form-0 `cooldown: null` on at least one of Q/W/E/R and
  fall to a hardcoded `return 60.0` placeholder at `ability_dps.py:511`.
- **Four of those 11 are also in the measured-zero set** (Aphelios E, Teemo E,
  Vayne W, Vi W). For those the pipeline divides a synthetic 60.0s placeholder
  by `(1 + AH/100)` and feeds the result straight into DPS. That is the majority
  of the six live pairs.

Fixing the model before fixing this data would be building on sand.

## 6. What is cheap here, and separable - ALL FOUR SHIPPED (ENGINE 1.221.0)

These are real, small, and independent of the deferred model work. None is
required to close RM-92. All four landed 2026-07-18 in the slice immediately
following this verdict. **Item 2 turned out materially bigger than written
below** - see the correction recorded under it.

1. **Mislabelled ARAM field, fires in SR.** `ability_dps.py:1454` assigns
   `aram_ability_haste=total_ah`, but `total_ah` includes item AH, so an SR
   build with Cosmic Drive reports `aram_ability_haste: 35.0`. Same mislabel in
   the note text at `:1426-1430`. Tier-2 (touches a scorer output field).
2. **Champion-name key mismatch**, section 4: 21 champions silently take the
   global fallback instead of their own measured rates. Affects far more than
   ability haste - it is a cast-rate accuracy bug across `ability_dps.py`.
3. **Three stale comments that assert the opposite of the code.**
   `engine.py:268` ("Exposure-only; no scorer reads it yet") and
   `engine.py:237-238` ("no engine consumer for ability-haste exists in the
   current scorer suite") are both falsified by `ability_dps.py:639`, which
   consumes `aram_ability_haste`. `augment_formula_eval.py:69` cites
   `ability_dps.py:49` for "the engine has no AH model"; that line is now about
   on-cast triggers and says nothing about AH. Tier-0.
4. **Registry docstring cites a tool that has never existed.**
   `_item_ability_haste.py:20` cites `tools/regen_item_ability_haste.py`;
   repo-wide glob returns nothing. The whole "Regeneration:" paragraph
   (`:18-29`) documents a workflow with no implementation. Only the drift
   checker `ops/audit/item_ah_drift_check.py` (103 lines) is real, and it is
   effectively the missing generator's parse half minus the emit step. The
   registry itself is healthy: 309 lines, **220 items**, hand-pinned. Tier-0
   docstring fix, or promote the checker to a real regen tool.

### What actually shipped, and where this section was wrong

**Item 1 - fixed outright.** A consumer trace proved the field is WRITE-ONLY in
production: declared `ability_dps.py:815`, serialized `:842`, exposed only on
`POST /ability-dps`, never carried by `/rank-mage`, never printed by
`format_table`. Zero readers outside tests, so no score or ranking moved. The
un-mode-gated NOTE was worse than the field - an SR run literally printed
`ARAM aramAbilityHaste=+25 on per-spell cooldowns`, which a human actually
sees. Both fixed. Both pre-existing tests passed `item_ids=[]` and therefore
never exercised the divergent case; a new 8-test class does.

**Item 2 - UNDERSTATED HERE IN TWO WAYS. Shipped DEFAULT-OFF.**

- This section called it a bug "across `ability_dps.py`". It is **four call
  sites across three modules**: `ability_dps.py:1228` (spell casts),
  `ability_dps.py:1349` (ult casts into item procs), `dps.py:1023` (carry /
  Malignance), `ability_hps.py:900` (HPS). Two of those were unknown when this
  document was written.
- Section 4 implied the correction was a per-champion rescale. It is not.
  `global_fallback` is a per-spell VECTOR, so fixing the key is a per-spell
  REWEIGHT. A uniform scale would have preserved item order exactly (`delta`
  and `ability_dps_per_1k_gold` scale by the same constant); the reordering is
  entirely attributable to the reweight. Within-champion ratios swing hard -
  Bel'Veth Q 3.64x but W 0.82x, Kog'Maw R 4.18x but Q 0.58x.
- Measured flag-ON: **13 of 21 champions reorder** on the ability scorer
  (Kha'Zix sharpest - Blackfire Torch falls #2 to outside the top 15), 3 of 21
  on carry but only with Malignance already owned, plus an unmeasured
  structurally identical reweight on HPS.

Because it is not byte-identical, it ships behind DEFAULT-OFF
`apply_canonical_cast_rate_keys`, fixed at the single `ult_rates.py`
chokepoint rather than the four callers (the parameter is literally named
`champion_name`; a caller-side patch leaves the trap armed for call site #5).
Reuses `core/archetype_picks.canonical_champion_id` via a lazy in-function
import, because `agents/daemon_slayer/` imports `core/` zero times in
production and the dependency runs the other way. Byte-identity at the default
is proven, not asserted: 3880 baseline lookups re-run post-fix, 0 diffs.
Live default-ON flip is operator-gated.

**Items 3 and 4 - fixed outright**, Tier-0 text. The registry docstring now
states plainly that no generator has ever existed and points at the drift
checker as the real tool.

## 7. If it is ever built, the order is

1. Data first: close the Locke/Zaahen gap and the 11 null-cooldown champions,
   else the model reads a 60.0s placeholder.
2. Fix the display-name/DDragon-id lookup so measured rates land.
3. Decide the modelling question that actually blocks this, which is NOT
   plumbing: **should haste modulate a measured cast rate at all?** Today
   measured wins and haste is discarded. A defensible answer needs either a
   haste-normalized rate table or an explicit rotation model.
4. Only then does an AH term in `dps` / `hybrid` have anything to compress, and
   at that point it IS RM-39 / RM-43, not a separate build.

## Sources

Live probe `:8893/health`; `data/daemon_slayer/spell_cast_rates.json`;
`data/daemon_slayer/16.14.1/champion_abilities.json`;
`data/daemon_slayer/16.14.1/champions.json`. Every file:line above was read
this session or verified by direct probe.
