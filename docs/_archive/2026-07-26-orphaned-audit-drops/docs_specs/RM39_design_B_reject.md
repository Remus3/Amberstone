# RM-39 / RM-43 - Design B (the NULL shape): "haste must not modulate a measured rate"

Assigned position: kill the haste program. Argue the measured cast rate already
embeds population ability haste, so any haste multiplier double-counts, and the
Shojin failure has a different root cause that a haste term would paper over.

**VERDICT: my assigned shape is REFUTED. I could not kill the haste program.**

It is refuted by my own probe, not by someone else's argument. What survived is
narrower and differently-shaped than the ROADMAP's one-line framing, and one half
of my assigned alternative root cause turned out to be not just correct but
DOMINANT and GATING. Details below, evidence first.

Date: 2026-07-18. Engine 1.221.0, patch 16.14.1, DS live on :8893 (verified
`/health` this session). No production code was written or modified.

---

## 1. Direct answer to the blocking question

**SHOULD ABILITY HASTE MODULATE A MEASURED CAST RATE AT ALL?**

**YES, conditionally - but only as a RELATIVE correction against the population
haste the rate was observed at, and it is provably worthless on its own.**

The strong form of my assigned position ("never") is dead. The weak form
survives and is worth stating precisely, because the ROADMAP's framing commits
the exact error the weak form warns about:

- Multiplying the measured rate by a factor derived from the build's TOTAL
  ability haste IS a double-count. That is the naive shape and it should be
  rejected.
- Multiplying by `cd(pop_ah) / cd(build_ah)` is NOT a double-count. It prices
  only the haste DELTA over the population the observation came from. It is
  well-defined, and the denominator is derivable from data already on disk.

So the honest answer is not "no". It is "yes, but the quantity is a ratio
against a baseline that the current dataset does not carry, and building that
baseline is part of the work."

### What actually killed the null shape

I ran the 2x2 that the null shape predicts should be flat. It is not flat.

Probe: `compute_ability_dps`, Aatrox and Ambessa, level 13, SR, core
`[6610 Sundered Sky, 3047 Plated Steelcaps, 6333 Death's Dance]`, target
100 armor / 70 MR / 2400 HP, 13 realistic candidates. Shojin's rank among them:

| condition | cast rate | Shojin AH in registry | Aatrox | Ambessa |
|---|---|---|---|---|
| A status quo | measured | absent | 8/13 | 7/13 |
| B registry fix only | measured | present | **8/13 (no change)** | **7/13 (no change)** |
| C haste credited only | theoretical | absent | **9/13 (worse)** | **8/13 (worse)** |
| D both | theoretical | present | **3/13** | **3/13** |

Neither fix does anything alone. Together they move Spear of Shojin from
mid-pack to top-3 on both champions simultaneously. Shojin's delta goes
3.863 -> 23.630 on Aatrox (6.1x) and 2.335 -> 14.884 on Ambessa (6.4x).

A pure interaction effect of that size is not something a "different root
cause" explains away. Haste is load-bearing. My assigned shape is wrong.

### What replaced it (the shape I actually recommend)

Condition D credits the FULL build haste against the base cooldown, i.e. it
treats the empirical observation as if it were taken at zero haste. That IS the
double-count I was assigned to find, and it is real - it inflates Aatrox
baseline ability DPS from 26.37 to 63.87 (+142%), which would reorder every
champion on the ability scorer, not just these two.

The surgical version keeps the measured rate and scales only by the delta:

```
rate_build = rate_measured * (cd_at_pop_ah / cd_at_build_ah)
cd(ah) = base_cd * 100 / (100 + ah)
```

Measured population median item AH, from `data/rewind_history.db`
(`participants.item0..item5` joined to `matches.queue_id in (420,400,430,440,700)`,
Shojin patched in-memory so the number is truthful): **Aatrox 32.5 (n=36),
Ambessa 40.0 (n=48)**.

Result with the surgical correction (registry fixed, measured rate PRESERVED):

| | Shojin rank | baseline ability DPS |
|---|---|---|
| Aatrox status quo | 8/13 | 26.37 |
| Aatrox surgical | **3/13** | 24.88 (-5.6%) |
| Ambessa status quo | 7/13 | 21.43 |
| Ambessa surgical | **3/13** | 19.22 (-10.3%) |

Same corrected rank as condition D, without the 142% baseline explosion. This
is the shape that should ship. It is a defensible counterfactual rather than an
upper bound.

---

## 2. The finding that outranks the whole haste question

**On the production route, none of the above reaches Aatrox or Ambessa at all.**

`ds.hybrid` (served as `POST /rank-bruiser`) branches on damage axis:

`agents/daemon_slayer/hybrid.py:462-468` (verified this session)

```python
    if _damage_axis(snapshot, champion_id) == "ap":
        base_damage = _ability_damage(
            snapshot, champion_id, level, item_list, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp, augments,
        )
    else:
        base_damage = dps_result.weighted_dps
```

`_damage_axis` (`hybrid.py:73-79`) returns `"ap"` only when
`info.magic > info.attack`. From `data/meta/ddragon_champions.json`:
Aatrox `(attack 8, magic 3)`, Ambessa `(attack 9, magic 0)`. Both take the
`else` branch. `dps_result.weighted_dps` is `compute_dps()`, whose own module
docstring at `agents/daemon_slayer/dps.py:34` states:

> Ability damage is **not** included - spell formulas aren't in the snapshot.

Measured directly, by counting calls through a full 140-candidate ranking:

```
Aatrox   axis=ad   compute_ability_dps calls=0
Ambessa  axis=ad   compute_ability_dps calls=0
Veigar   axis=ap   compute_ability_dps calls=140
```

**`compute_ability_dps` is the only function in the engine that reads ability
haste, and it is invoked zero times for both RM-39 and RM-43 champions.**

Three consequences:

1. Every result in section 1 was produced on `/rank-mage`, a scorer these
   champions do not use in production. Conditions B, C and D all change the
   live `/rank-bruiser` output by exactly zero positions.
2. The ROADMAP instruction "credit ABILITY HASTE in the hybrid DPS term" is
   **not well-formed as written**. There is no ability term in the hybrid AD DPS
   branch to credit haste into. Haste modulates cooldowns; cooldowns only matter
   if ability casts are being counted; the AD branch counts zero.
3. It is worse than a missing term. `dps.py:34-38` notes that rotation duration
   includes ability cast time, so casting is scored as auto-attack DOWNTIME that
   DILUTES the result. An ability-centric bruiser is actively penalised for
   using his kit.

This is the half of my assigned alternative that held: **the hybrid AD branch
prices sustained auto DPS only.** ROADMAP RM-39 names the Q-sweetspot clause
first, before the haste clause, and that ordering is correct - but the
underlying defect is more general than the Q sweetspot. It is not that one spell
is mismodelled. It is that no spell is modelled.

BotRK ranking #1 is then not a mystery and not a valuation error: sustained
auto-attack DPS is the only quantity being maximised, and BotRK is the best
sustained-auto item in the pool. Live probe at build depth confirms it is not
an `item_ids=[]` artifact - with three core items owned, BotRK is #1 of 138
(delta_dps 63.51) and Spear of Shojin is **#45 of 138** (delta_dps 11.99, all of
it raw AD).

---

## 3. Second finding: Spear of Shojin is missing from the ability-haste registry

`agents/daemon_slayer/_item_ability_haste.py:49` `_ITEM_ABILITY_HASTE` holds 220
items. Item `3161` Spear of Shojin is **absent**, as is its Arena mirror `223161`.

```
total_item_ability_haste(['6610','3047','6333'])          = 25.0
total_item_ability_haste(['6610','3047','6333','3161'])   = 25.0   <- unchanged
```

DDragon `3161` description: `<passive>Dragonforce</passive> Gain 25 Basic
Ability Haste.` The haste is a named passive grant, not a `stats` entry, which
is why a hand-pinned registry missed it. The registry is otherwise healthy: I
scanned all 226 DDragon items whose description mentions ability haste against
the registry - 220 present, 6 absent, and of the 6 absent, **five are Arena-only
prismatics with no base id** (228002 Wooglet's Witchcap, 228005 Obsidian
Cleaver, 228006 Sanguine Blade, 228008 Runeglaive, plus 223161). Exactly one
base SR item is missing and it is Spear of Shojin.

The single item whose misranking constitutes the entire evidentiary basis for
RM-39 and RM-43 is the single item the ability-haste registry cannot see. Note
also that it is **Basic** ability haste - Q/W/E only, not R - so the correct
model excludes the ultimate. My surgical probe honors this.

Memory `reference_item_ah_registry_drift` already records that this registry is
hand-pinned with a drift checker (`ops/audit/item_ah_drift_check.py`) but no
regen tool. This is that drift, found.

---

## 4. Model shape, seams, flag

Three defects in strict dependency order. Defect 1 gates 2 and 3; 2 and 3 are
inseparable from each other (proven by the 2x2).

### Defect 1 (GATING) - hybrid AD branch has no ability term
- Seam: `agents/daemon_slayer/hybrid.py:462-468`
- Shape: the AD branch must combine auto DPS with ability DPS rather than
  selecting one. The AP branch already replaces autos with abilities, which is
  its own approximation; an AD bruiser needs both. Suggested:
  `base_damage = dps_result.weighted_dps + _ability_damage(...)`, which requires
  confirming `dps.py` rotation duration does not already double-charge the
  cast-time window.
- Flag: `assume_ad_ability_damage` (DEFAULT-OFF)
- This is the expensive one and it is not RM-39-specific. It changes every
  AD-axis champion routed to `ds.hybrid`.

### Defect 2 - Shojin absent from the AH registry
- Seam: `agents/daemon_slayer/_item_ability_haste.py:49` `_ITEM_ABILITY_HASTE`
- Shape: add `"3161": 25.0` and `"223161": 25.0`. Strictly this needs a
  basic-vs-ultimate distinction the registry does not currently carry; the
  cheap correct version is a second dict of basic-only ids consumed at
  `ability_dps.py:1113`.
- Flag: none needed if basic/ultimate is modelled; if shipped as flat AH it
  over-credits R and should be flagged.

### Defect 3 - the haste-shortened cooldown is discarded
- Seam: `agents/daemon_slayer/ability_dps.py:1252-1259` (verified this session;
  the LEDGER's `:1231-1234` has drifted)

```python
        measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)
        cps_source = "measured"
        mana_uptime = 1.0
        if measured <= 0:
            theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0
            mana_uptime = _mana_uptime_factor(cost, cooldown, ctx, form.resource)
            measured = theoretical * mana_uptime
            cps_source = "theoretical_with_mana_uptime" if theoretical > 0 else "missing"
```

  `cooldown` is bound at `ability_dps.py:1185-1188` via `_effective_ability_cd`
  (`ability_dps.py:522`) and is already correct - the engine computes AH=25 and
  Q 6.00s -> 4.80s on every build, then throws it away whenever `measured > 0`.
- Shape: the surgical relative correction from section 1, applied to Q/W/E only.
- New data: one field per champion x mode in
  `data/daemon_slayer/spell_cast_rates.json`, e.g. `"pop_item_ah": 32.5`,
  emitted by `scripts/build_spell_cast_rates.py` (the DB already carries
  `participants.item0..item5`; the existing `total_item_ability_haste` does the
  rest).
- Flag: `apply_haste_relative_cast_rate` (DEFAULT-OFF), at the
  `ult_rates.py` chokepoint rather than the four call sites, matching the
  precedent set by `apply_canonical_cast_rate_keys` in ENGINE 1.221.0.

**There is no new haste MODEL to build.** `_effective_ability_cd` already exists,
is already called, and is already correct. Defect 3 is a branch-arbitration
question, not a modelling one.

### Provenance note (sub-question 1, answered)

`agents/daemon_slayer/ult_rates.py:14-16` and the file's own metadata:

```
source = "data/rewind_history.db (2851 matches, spell[1-4]_casts / game_duration_s)"
```

That is total casts over TOTAL GAME DURATION. It is a **whole-game average**,
not an in-combat rate - it includes walking, laning, recalling, and dead time.
`scripts/build_spell_cast_rates.py:5-7` asserts the rate "already encodes
mana/cooldown downtime, so no separate uptime modeling is needed", which is true
as far as it goes and quietly understates what else it encodes.

Measured ratio of the observed rate to the theoretical rate at the already-hasted
cooldown, level 13, AH=25:

| | base CD | eff CD | measured | theoretical | ratio |
|---|---|---|---|---|---|
| Aatrox Q | 6.00 | 4.80 | 0.10108 | 0.20833 | 0.485 |
| Aatrox W | 12.00 | 9.60 | 0.02130 | 0.10417 | 0.205 |
| Aatrox E | 9.00 | 7.20 | 0.06285 | 0.13889 | 0.453 |
| Ambessa Q | 10.00 | 8.00 | 0.08186 | 0.12500 | 0.655 |
| Ambessa E | 13.00 | 10.40 | 0.03808 | 0.09615 | 0.396 |

Both champions are manaless, so `mana_uptime` is 1.0 and the theoretical column
is pure `1/cd`. About half of Aatrox's Q casts are not blocked by cooldown at
all. This is the one part of the null shape that remains materially true and it
feeds directly into the strongest objection below.

Sub-question 2 (double-count) is answered above: yes for the naive full-build
multiplier, no for the relative correction. Sub-question 3 (counterfactual) is
answered: a population median genuinely cannot answer a counterfactual about an
unobserved build, but the ratio form only asks it to supply a BASELINE, which is
a much weaker and satisfiable demand. Sub-question 4 is answered in section 2.

---

## 5. What would change in ranking

Probed, not predicted. `/rank-mage`, level 13, SR, core three items, 13 candidates:

- Aatrox: Shojin 8/13 -> **3/13**. Delta 3.863 -> 9.349 under the surgical
  shape, 23.630 under the theoretical flip.
- Ambessa: Shojin 7/13 -> **3/13**. Delta 2.335 -> 6.174 surgical.
- Serylda's Grudge and Black Cleaver stay #1 and #2 in every condition, which is
  plausible for both champions and suggests the correction is not simply
  inflating whatever carries haste.
- BotRK on the ability scorer sits at **42/138** versus **1/138** on the live
  hybrid scorer. The gap between those two numbers is the size of defect 1.

Live `/rank-bruiser` (production) change from defects 2 and 3 alone: **zero
positions**, for the reason in section 2. That is the single most decision-relevant
number in this document.

---

## 6. Honest cost estimate

| item | tier | estimate |
|---|---|---|
| Defect 2, registry entry + basic-only handling | Tier-2 | 0.5 session |
| Defect 3, `pop_item_ah` in the rate builder + regenerate JSON | Tier-2 | 0.5 session |
| Defect 3, relative-correction seam + flag at the `ult_rates` chokepoint | Tier-2 | 1 session |
| Defect 1, hybrid AD ability term | Tier-2 | 2 to 3 sessions |
| Cross-roster regression sweep for defect 1 | Tier-2 | 1 session |
| **total** | | **5 to 6 sessions** |

Defects 2+3 alone are about 2 sessions and produce **no live ranking change**.
They are only worth doing as a prerequisite to defect 1, or behind a flag as
groundwork. Sequencing 2+3 first and declaring progress would be a false
positive - the live output is byte-identical.

Defect 1 is the real cost and its blast radius is every AD champion on
`ds.hybrid`, not the two named in RM-39/RM-43. It needs the full dual suite and
a per-champion sweep, and it will surface the same "which scorer is
authoritative" question for on-hit and bruiser routes.

---

## 7. Strongest argument against my own recommended shape

Not against the assigned shape, which is already dead. Against the surgical
relative correction I ended up recommending.

**The correction assumes the elasticity of cast rate to ability haste is exactly
1.0, and the data says it is probably closer to 0.5.**

`rate_build = rate_measured * cd(pop_ah)/cd(build_ah)` assumes every cast the
player did not make was blocked by cooldown. The ratio table in section 4 says
otherwise: Aatrox Q sits at 0.485 of the theoretical hasted rate, so roughly half
his missing casts are engagement-limited, not cooldown-limited. Shortening a
cooldown does not manufacture a target to cast at. The correction should
therefore be damped, something like

```
rate_build = rate_measured * (1 + e * (cd(pop_ah)/cd(build_ah) - 1))
```

with `e` defaulting near the observed measured/theoretical ratio rather than 1.0.

**I ran this probe rather than leaving it as a caveat, and it partially
rehabilitates the skepticism I was assigned.** Shojin's rank is sensitive to `e`:

| e | Aatrox Shojin rank | Ambessa Shojin rank |
|---|---|---|
| 0.00 (status quo) | 8/13 | 7/13 |
| 0.25 | 7/13 | 6/13 |
| **0.485 (the measured Aatrox Q ratio)** | **6/13** | **4/13** |
| 0.50 | 6/13 | 4/13 |
| 0.75 | 4/13 | 3/13 |
| 1.00 (undamped) | 3/13 | 3/13 |

The top-3 result in section 1 exists only at `e = 1.0`, which is precisely the
assumption the ratio table contradicts. At the empirically motivated `e = 0.485`
Aatrox's Shojin reaches only 6th, behind Eclipse. **The haste program's headline
result is therefore parameter-dependent on a free parameter nobody has measured**,
and the honest reading is that haste moves Shojin roughly two to four places
rather than into the core. Whoever ships this must either justify `e = 1.0`
against the 0.485 observation or accept a materially weaker fix.

Two further objections I could not resolve:

- **Confounded denominator.** `pop_item_ah` is derived from the same games as the
  cast rate. Players who build haste may also be players who fight more, so part
  of the rate/haste association is behavioural rather than mechanical. Dividing
  by `pop_ah` silently attributes all of it to cooldowns and over-credits haste
  by an unknown amount.
- **Thin samples.** n=36 for Aatrox and n=48 for Ambessa. The builder's
  `MIN_SAMPLES = 5` policy admits these, but a per-champion median item AH from
  36 games is noisy, and it is a per-patch quantity being applied to a 16.14.1
  item pool from a rate file generated 2026-05-12.

The honest summary is that defect 2 is certain and cheap, defect 1 is certain and
expensive, and defect 3 - the actual haste question - is real but is the piece I
am least confident is correctly shaped.

---

## 8. Bottom line

- Assigned null shape: **REFUTED**, by my own 2x2. Haste is load-bearing.
- ROADMAP framing "credit ability haste in the hybrid DPS term": **not
  well-formed** - that branch has no ability term.
- Real cause of RM-39 / RM-43: a **three-defect conjunction**, dominated and
  gated by the hybrid AD branch scoring auto-attacks only.
- Cheapest real bug found: **Spear of Shojin is missing from the 220-item
  ability-haste registry**, and it is the only base SR item missing.
- What I was right about: the AD branch prices sustained autos only, and the
  measured rate is a whole-game average rather than an in-combat rate. The
  second fact has teeth - damping the correction by the observed 0.485
  engagement ratio drops Shojin from 3rd back to 6th on Aatrox.
- What I was wrong about: that these facts make haste unnecessary. They do not.
  They make haste insufficient, and parameter-sensitive.

Recommended sequencing if the judges adopt any of this: **defect 2 first**
(one registry line, certain, cheap), **defect 1 second** (the real fix, and the
only one that changes live output), **defect 3 last and behind a flag**, with the
elasticity `e` treated as an open question rather than pinned at 1.0.
