# RM-39 / RM-43 - Design D: "combat rotation is cooldown-bound"

Assigned shape: argue that a whole-game measured cast rate and an in-combat DPS
term are different quantities, that a bruiser inside a fight is COOLDOWN-BOUND,
and that a bounded-rotation model (reusing `mana_sim`) should replace the
measured median.

Status: **DIAGNOSIS CONFIRMED. PRESCRIPTION REFUTED.**
Engine 1.221.0, patch 16.14.1, probed live on `:8893` 2026-07-18.

I was asked to make the strongest honest case for this shape. The diagnosis half
survives contact with the evidence and is worth keeping. The prescription half
does not, and two findings I did not expect make the whole RM-39 framing wrong.
I am reporting the refutation rather than defending the assignment.

---

## 1. Answer to the blocking question

> SHOULD ABILITY HASTE MODULATE A MEASURED CAST RATE AT ALL?

**NO.** Multiplying a measured population median by a build-derived haste factor
is a category error, and it is also empirically inert - it changes nothing.

The category error: the measured rate is an OBSERVATION of a population that
already built whatever haste it built. A haste multiplier is a COUNTERFACTUAL
about a build that population may never have run. The product of an observation
and a counterfactual is neither.

The empirical proof is stronger than the argument, and it is row C of the
ablation in section 6: registering Spear of Shojin's real ability haste while
leaving the measured rate in place moves Shojin **exactly zero ranks** (Aatrox
#40 -> #40, Ambessa #37 -> #37). Under `measured`, haste is not merely
double-counted, it is structurally unreachable. `dps = post_mit * measured` at
`ability_dps.py:1261` has a nonzero derivative with respect to AD/AP items
(through `post_mit`) and an EXACTLY ZERO derivative with respect to every
cooldown and haste item in the game.

So the blocking question has a clean answer. But it turns out to be the wrong
question for RM-39/RM-43, for the reason in section 4.

---

## 2. Sub-question 1 - PROVENANCE (whole-game, confirmed)

The measured rate is a **whole-game average**, not an in-combat rate. Verified
at the generator, not inferred:

- `scripts/build_spell_cast_rates.py:128-131` - `"Q": (q_casts or 0) / dur`,
  and `dur` is `m.game_duration_s` selected at line 107-110.
- Line 112 filters `AND m.game_duration_s > 60` - the only duration gate.
- `ult_rates.py:14-16` states the same contract: "derived from
  `rewind_history.db.participants.spell[1-4]_casts / matches.game_duration_s`".

The denominator is total game duration. It includes laning downtime, walking,
recalling, being dead, and the entire pre-level-6 window during which the
ultimate cannot be cast at all.

The magnitude is not subtle. Measured SR rates for Aatrox, against the engine's
own haste-adjusted cooldowns at level 13 with Sundered Sky + Death's Dance +
Steelcaps (`total_ability_haste = 15`):

| key | eff cd | measured casts/s | implied period | 1/cd | ratio |
|---|---|---|---|---|---|
| Q | 5.22s | 0.10108 | one per 9.9s | 0.1917 | 1.9x |
| W | 10.43s | 0.02130 | one per 46.9s | 0.0958 | 4.5x |
| E | 7.83s | 0.06285 | one per 15.9s | 0.1278 | 2.0x |
| R | 86.96s | 0.00498 | **one per 201s** | 0.0115 | 2.3x |

An Aatrox ultimate once every 201 seconds is a defensible number for a game
average and an indefensible one for a teamfight. The quantity is wrong for the
term it feeds.

Honest calibration note: I expected 10x dilution and found 1.9x-4.5x. The
whole-game average is less diluted than the category error implies, because
`spell1_casts` counts each link of a recast chain separately. The direction of
the argument holds; the magnitude is smaller than the shape assumes.

## 3. Sub-questions 2 and 3 - DOUBLE-COUNT and COUNTERFACTUAL

**DOUBLE-COUNT: real in principle, moot in practice.** The median is taken over
players who already build haste, so a haste multiplier on top would
double-count. But this objection only bites a "multiply measured by haste"
shape. It does not bite a "replace measured" shape, which is what D proposes.
And row C shows there is currently nothing to double count.

**COUNTERFACTUAL: fatal, and this is the real argument for D.** A build ranker
asks "what happens if I buy THIS item". `get_spell_casts_per_sec`
(`ult_rates.py:201`) is a lookup keyed only by `(champion, key, mode)`. It has
no build argument. It CANNOT answer a counterfactual about a build it never
observed, and it returns the identical scalar for a naked champion and a
six-item one. For the haste dimension specifically, the ability term is a
constant that cancels between baseline and candidate. That is a structural
defect, not a precision problem, and no amount of better data fixes it - the
function has no parameter to vary.

## 4. Sub-question 4, and the finding that reframes RM-39

`dps.py` has **no ability model at all**, as stated. `dps.py:1023`
`ult_casts_per_sec = get_ult_casts_per_sec(...)` feeds `CallContext` at :1039
and is consumed only by item proc rates (Malignance Hatefog). It is an
empirical median from the same whole-game source. There is no ability damage in
`compute_dps`.

That matters far more than it first appears, because of the seam at
`hybrid.py:462-468`:

```
462:    if _damage_axis(snapshot, champion_id) == "ap":
463:        base_damage = _ability_damage(
...
468:        base_damage = dps_result.weighted_dps
```

mirrored in the ranker at `hybrid.py:944-945`. AP-axis champions are scored on
ability DPS. **AD-axis champions are scored on auto-attack DPS only.**

Resolved live via `_damage_axis`: Aatrox `attack=8 magic=3 -> ad`. Ambessa
`attack=9 magic=0 -> ad`. Instrumented proof (spy wrapper on
`hybrid.compute_ability_dps`, one `compute_hybrid` call each):

```
Aatrox         ability_dps calls inside compute_hybrid = 0
Ambessa        ability_dps calls inside compute_hybrid = 0
Mordekaiser    ability_dps calls inside compute_hybrid = 1
```

**The seam RM-39 and RM-43 are written against is unreachable for the two
champions they name.** `ability_dps.py:1252-1259` never executes for Aatrox or
Ambessa. Their ability damage - a real 27.2 and 22.0 DPS at that build, which is
itself understated by the measured rate - is discarded before any cast-rate
question arises. 92 of 173 champions are `axis=ad`.

This is why BotRK is #1 and Shojin is not. BotRK is an auto-attack item and the
AD bruiser score is an auto-attack score. Shojin's 45 AD earns a little
auto-attack DPS and its 450 HP earns EHP; its ability haste and its ability
damage amp are both invisible because there is no ability term to be visible in.
It is a MODEL gap exactly as RM-39 claims - but the gap is a missing damage
term, not a missing haste term.

### 4b. Second finding: Shojin's haste is not in the engine at all

`total_item_ability_haste(["3161"])` returns **0.0**. This is not registry
drift. Spear of Shojin in 16.14.1 carries its haste in a passive:

```
45 Attack Damage | 450 Health
Dragonforce: Gain 25 Basic Ability Haste.
Focused Will: ... increases Ability and Passive damage by 3% for 6s (stacks 4).
```

The `<stats>` block is AD and Health only. `_item_ability_haste.py`'s docstring
states the parser reads the FIRST `<stats>` block and that "conditional /
passive-granted AH is invisible to the checker by design". Shojin's 25 Basic
Ability Haste falls in that blind spot.

I swept all 16.14.1 purchasable items for the same pattern (haste in passive
text, 0.0 in the registry). Exactly **two** hits: `3161` and its Arena mirror
`223161`. Both are Spear of Shojin. The data gap is real, precisely bounded, and
two lines wide.

---

## 5. The model shape, seam, and flag

Shape D as a model: inside a fight of length T, casts follow from cooldown, so

```
in_combat_cps(spell) = (1 + T / eff_cd) / T  =  1/T + 1/eff_cd
```

with `eff_cd = base_cd / (1 + AH/100)` (`_item_ability_haste.py:293`).

**Exact seam** - `agents/daemon_slayer/ability_dps.py:1252-1259` (verified this
session; the LEDGER's `:1231` has rotted):

```
1252:        measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)
1253:        cps_source = "measured"
1255:        if measured <= 0:
1256:            theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0
1258:            measured = theoretical * mana_uptime
1259:            cps_source = "theoretical_with_mana_uptime" if theoretical > 0 else "missing"
```

`cooldown` at 1256 is already haste-shortened - `base_ah` is summed at
`ability_dps.py:1113` and folded at `:1114`, and the result is reported out at
`:1288`. The engine computes the haste-corrected cooldown, stores it, and then
does not use it for the DPS number.

**Flag:** `apply_cooldown_bound_cast_rate: bool = False` (DEFAULT-OFF), matching
the `apply_canonical_cast_rate_keys` / `apply_ability_haste` convention. ON
swaps the primary branch to `1/eff_cd`; OFF is byte-identical.

**Prior art check (assigned): `mana_sim` already does this, and reusing it buys
nothing here.** `mana_sim.py` is a real bounded-rotation walker - haste-scaled
cooldown at `:296-297` via the shared `effective_cooldown`, wait-for-ready at
`:307-310`, `apply_ability_haste` opt-in at `:506`, `_MAX_DURATION_S = 180.0` at
`:99`. It is production code behind `fight_report`, `matchup`,
`scenario_matrix`, and `core/laning_scenario_precompute`, and it is wired into
**zero rankers**. But it is sequence-driven: it needs a `combo_sequence` and it
returns a rotation wall-clock, not a per-spell rate. Routing a 140-candidate
ranking sweep through a two-pass burst-walker simulation per candidate is orders
of magnitude more compute for a number that, as section 7 shows, collapses to
`1/eff_cd` anyway.

**`fight_length` is not a fight length.** `rank.py:890` is
`effective = burst_delta + delta_dps * fight_length`, a burst/sustain blend
weight; the calibrated Jhin value is `0.5`. It cannot supply T. The only real
combat-duration constant in the engine is
`_passive_survival_window_overrides._DEFAULT_FIGHT_WINDOW_S = 6.0`.

---

## 6. What would change in ranking (probed)

Live `/rank-bruiser`, Aatrox and Ambessa, level 13, SR, target 100 armor / 70 MR
/ 2400 HP, at real build depth `["6673","6333","3047"]` (Sundered Sky +
Death's Dance + Plated Steelcaps), `top=200`.

Shipped baseline, both champions reproduce the RM-39 complaint:

| champion | BotRK | Shojin | baseline_dps | baseline_ehp |
|---|---|---|---|---|
| Aatrox | **#1** (pct 0.5770) | **#43** (pct 0.1923) | 59.07 | 5370 |
| Ambessa | **#1** (pct 0.6089) | **#38** (pct 0.2035) | 108.50 | 5207 |

Ablation, offline sim mirroring the ranker. Sort key verified by reconstruction:
`hybrid_delta_pct = alpha*(d_dps/baseline_dps) + beta*(d_ehp/baseline_ehp)`
(`hybrid.py:713-734`); BotRK checks as `0.5*2.4219 + 0.5*0.04935 = 1.2356`,
matching the server to 4 decimals. Sim validation: top-1 reproduces the server
exactly for both champions; Shojin lands within 1 rank (sim #42 vs server #43;
sim #37 vs server #38), so read the rows against row A, not against the server.

| # | variant | Aatrox Shojin | Ambessa Shojin |
|---|---|---|---|
| A | shipped (no ability term) | #42 | #37 |
| B | + ability term, MEASURED rate | #40 | #37 |
| C | + ability term, MEASURED, **+ Shojin AH registered** | **#40** | **#37** |
| D | + ability term, **1/eff_cd (SHAPE D)** | **#44** | **#44** |
| E | SHAPE D + Shojin AH registered | **#13** | **#21** |

Read this honestly:

- **C is the answer to the blocking question.** Correct haste data + measured
  rate = zero movement. Haste is discarded, exactly as claimed.
- **D is the refutation of my own shape.** Shape D applied ALONE makes the target
  case WORSE on both champions (#42 -> #44, #37 -> #44).
- **E is where the value is, and the value is in the data fix, not the model.**
  D -> E is a two-line registry change and it is worth 31 and 23 ranks.
- **BotRK is still #1 or #2 in every single variant.** The headline symptom
  "BotRK #1 at every target and level" is NOT fixed by any of this. Whatever
  makes BotRK dominate an AD bruiser is a separate defect.

---

## 7. Cost

Shape D alone is small; the stack that makes it worth anything is not.

| piece | scope | est |
|---|---|---|
| Register Shojin 25 AH (`3161`, `223161`) + drift-checker exemption + test | 2 registry lines | 0.5 session |
| Shape D flag at `ability_dps.py:1252-1259` | ~6 lines + flag plumb | 0.5 session |
| Re-baseline every ability consumer under the flag | `/rank-mage`, `/rank-onhit`, `ability_hps`, 81 AP champions | 1.5 sessions |
| Ability term on the AD hybrid branch (`hybrid.py:462-468` + `:944-945`) | 92 champions, changes `baseline_dps` denominator for every AD bruiser | 2-3 sessions |
| Damage-type guard for the above (see risk below) | new | 1 session |

**Total 5.5 - 6.5 sessions**, of which Shape D itself is ~2 and is net-negative
without the rest. The risk is concentrated in the routing change, not in my
shape.

Live-flip note: the flag is a caller-default flip plus a DS `:8893` restart and
a Share mirror sync, per the standing seam convention. Tier-2 throughout.

New risk surfaced by row B: adding an ability term to the AD branch under the
measured rate promoted **Liandry's Torment to #1 for Aatrox**. An unfiltered
ability term imports AP burn items onto AD bruisers. Any routing change needs a
damage-axis or damage-type guard shipped in the same slice, which is the extra
session above.

---

## 8. Strongest argument against my own shape

**Shape D replaces a rate that is too low and haste-blind with a rate that is
too high and haste-oversensitive. Neither is the in-combat truth.**

`1/eff_cd` asserts perfect uptime - that a bruiser casts every ability the
instant it comes off cooldown, forever, never walking, never repositioning,
never missing, never CC'd. That is as wrong as the whole-game average, in the
opposite direction, and it is wrong in a way that systematically favors one item
class. Measured over the full 135-candidate pool for Aatrox:

```
items WITH ability haste   (n=55): median +10.0 ranks UP
items WITHOUT ability haste(n=80): median  -6.0 ranks
Black Cleaver     #19 -> # 4   (+15)
Serylda's Grudge  #30 -> #10   (+20)
Bastionbreaker    #38 -> #15   (+23)
Axiom Arc         #48 -> #18   (+30)
```

Shape D does not fix Shojin. It lifts the entire ability-haste class by a median
of ten ranks and Shojin rides along only once its 25 AH is registered. Axiom Arc
and Bastionbreaker are not Aatrox items. That is an indiscriminate reweight -
the signature of a tuning knob, not of a model correction. An honest in-combat
rate needs a cast-completion / uptime factor between the two bounds, and nobody
has measured one.

Second objection, on the assigned framing specifically: the literal
cooldown-BOUND rotation - discrete casts, `1 + floor(T/eff_cd)` - is
unshippable. Sweeping T for Aatrox with Shojin's haste registered:

```
T=  4  5  6  8 10 12 15 20 25 30
   33 14 32 33 14 33 16 15 21  9     <- Shojin rank, floor()
   12 12 12 12 12 12 13 13 13 13     <- Shojin rank, smooth
```

The discrete model swings 56 places between T=5 and T=10 as T resonates against
each spell's cooldown. Any shipped value of T would be a number chosen to
produce a desired ranking. The stable variant is stable precisely because
`(1 + T/eff_cd)/T = 1/T + 1/eff_cd` converges to `1/eff_cd` and T stops
mattering - which means the honest version of Shape D contains no fight model at
all. It is `theoretical` from `ability_dps.py:1256`, already written, currently
reachable only in the dead `measured <= 0` branch. "Build a bounded-rotation
combat model" reduces to "promote the existing fallback to primary".

---

## 9. Verdict

- The **diagnosis** is confirmed and worth keeping: the measured rate is a
  whole-game average (`build_spell_cast_rates.py:128-131`), it is the wrong
  quantity for a combat DPS term, and it makes ability haste structurally
  unreachable (row C).
- The **prescription** is refuted: a bounded-rotation model is unshippable in
  its discrete form, collapses to a 6-line flag in its stable form, gains
  nothing from `mana_sim` reuse, is net-negative on the target case alone (row
  D), and over-credits the whole haste class as a side effect.
- **RM-39 and RM-43 are misfiled.** They are written against
  `ability_dps.py:1252-1259`, which never executes for Aatrox or Ambessa
  (0 instrumented calls). Ranked by evidence, the defects are:
  1. **DATA** - Shojin's 25 Basic Ability Haste is unregistered
     (`_item_ability_haste.py`, 2 ids, worth 31 and 23 ranks in row E).
  2. **ROUTING** - the AD hybrid branch has no ability damage term at all
     (`hybrid.py:462-468`, `:944-945`, 92 champions).
  3. **MODEL** - the measured-vs-cooldown quantity error, which is the enabler
     for (1) and is worth nothing on its own.
- Recommend refiling as those three, doing (1) first because it is two lines and
  independently correct, and NOT funding a bounded-rotation combat simulator.
- Separately: **BotRK stays #1/#2 under every variant tested.** The RM-39
  headline symptom is unexplained by the haste hypothesis and needs its own
  investigation.

### Probe notes for whoever picks this up

- The route is **`/rank-bruiser`**. `/rank-hybrid` does not exist (404);
  `hybrid.py` IS the bruiser scorer.
- The item parameter is **`items`**, NOT `item_ids`. `item_ids` is silently
  ignored and the server ranks at EMPTY BUILD while echoing your request back.
  My first four probes hit this; `current_item_ids` in the response is the
  tell, and it is the documented empty-build artifact. Always check that echo.
- Sort key is relative, not absolute: `hybrid_delta_pct` (`hybrid.py:713-734`).
  Ranking by raw delta reproduces nothing.
