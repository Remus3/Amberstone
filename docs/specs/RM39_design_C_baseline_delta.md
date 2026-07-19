# RM-39 / RM-43 - Design C (baseline-relative haste delta): SELF-REFUTED

Session 2026-07-18. Read-only investigation. No production code written.
Assigned shape: **SHAPE C - BASELINE-RELATIVE HASTE DELTA**. Estimate each
champion's population baseline ability haste from `rewind_history.db`, then
scale the measured cast rate by the candidate build's haste delta against that
baseline.

Live DS probed BEFORE any claim: `GET :8893/health` -> `engine_version 1.221.0`,
`patch 16.14.1`, `champions 173`, `items 706`.

## VERDICT

**I am refuting my own assigned shape.** Shape C is dead, killed four
independent ways, any one of which is sufficient. The blocking question resolves
against it, and against every other haste shape as well.

Shape C's stated rationale is "accept that measured embeds population haste and
fix the double-count." I went looking for that double-count in the source data
and **could not find it**. Shape C is a correction for a bias that is not there.
Its central premise is falsified by the very database it proposed to draw the
baseline from.

Note also that the assigned framing (item haste is the lever) is factually
wrong on this patch for the item RM-39 names. See kill 4.

---

## THE BLOCKING QUESTION

> SHOULD ABILITY HASTE MODULATE A MEASURED CAST RATE AT ALL?

### ANSWER: NO. Not under this shape, and not under any shape, while the
### measured rate keeps its current definition.

The decisive measurement is **cooldown slack**: the ratio of casts the
already-haste-shortened cooldown permits to casts actually observed.

```
slack = (1 / eff_cd) / measured_casts_per_sec
```

Computed over all 173 champions at level 13 on a realistic 3-item build
(Profane Hydra + Black Cleaver + Sterak's Gage, 30 item AH), for every
(champion, spell) pair whose `casts_per_sec_source == "measured"`:

| spell | n | p25 | median | p75 | pairs with slack < 1.5 |
|---|---|---|---|---|---|
| Q | 171 | 3.02 | **4.06** | 5.51 | 3.5% |
| W | 166 | 3.14 | **4.46** | 6.97 | 3.0% |
| E | 168 | 2.33 | **3.26** | 5.10 | 5.4% |
| R | 171 | 2.13 | **2.70** | 3.18 | 10.5% |

**All spells: n=676, median slack 3.44x. Only 5.6% of pairs are cooldown-bound
(slack < 1.5).**

The anchors:

```
Aatrox    Q: eff_cd=  4.62s  measured 1 cast /   9.89s  SLACK= 2.14x
Aatrox    W: eff_cd=  9.23s  measured 1 cast /  46.94s  SLACK= 5.09x
Aatrox    E: eff_cd=  6.92s  measured 1 cast /  15.91s  SLACK= 2.30x
Aatrox    R: eff_cd= 76.92s  measured 1 cast / 201.00s  SLACK= 2.61x
Ambessa   Q: eff_cd=  7.69s  measured 1 cast /  12.22s  SLACK= 1.59x
Ambessa   W: eff_cd= 10.77s  measured 1 cast /  37.08s  SLACK= 3.44x
Ambessa   E: eff_cd= 10.00s  measured 1 cast /  26.26s  SLACK= 2.63x
Ambessa   R: eff_cd= 88.46s  measured 1 cast / 202.00s  SLACK= 2.28x
```

Aatrox's Q comes off cooldown every 4.62 seconds and he casts it once every 9.89
seconds. The cooldown is idle 53% of the time on the tightest spell in his kit,
and 71% of the time at the roster median. **Multiplying this rate by a haste
factor asserts that shortening a cooldown which already has 114% slack produces
more casts. It does not.**

Two framing notes, both of which make the answer stronger, not weaker:

1. `eff_cd` above **already includes** the build's 30 item AH
   (`ability_dps.py:1114` -> `_total_ability_haste`, `ability_dps.py:522`
   `_effective_ability_cd`). The slack is measured against the post-haste
   cooldown. Slack against base cooldown is larger still.
2. Aatrox Q fires **three casts per activation**, and `spell1_casts` counts all
   three. His true per-activation slack is therefore roughly 3x the 2.14x shown
   (about 6.4x). The table understates the case for exactly the champion RM-39
   is anchored on.

The structural reason is in the data definition, not in the noise. The measured
rate is an **engagement-frequency** statistic, not a **cooldown-limited** one.
Its binding constraint is opportunity: being alive, in range, and in a fight.
Haste only binds when a champion is cooldown-limited, which is 5.6% of pairs by
the permissive threshold and materially fewer in truth (see the caveat under
"Scope of any honest haste term").

---

## SUB-QUESTION 1 - PROVENANCE (investigated, not asserted)

**The measured rate is a WHOLE-GAME average. Confirmed at the source.**

`ult_rates.py:14-16` states the derivation; the builder proves it.
`scripts/build_spell_cast_rates.py:112` filters `m.game_duration_s > 60` and
joins participants to matches, then `:128`:

```python
"Q": (q_casts or 0) / dur,
```

where `dur` is `m.game_duration_s` - **whole game duration**. Not
`p.time_played`, not time alive, not time in combat.

Measured directly against `data/rewind_history.db` (2961 matches, 30562
participant rows): **median `time_spent_dead / game_duration` is 0.089, p90
0.161.** So roughly 9% of the denominator is time the champion was dead and
provably casting nothing, before counting laning, walking, recalling, warding,
and sieging.

This alone makes the measured rate the wrong quantity for a combat DPS term -
independent of haste. `ability_dps.py:1261` computes `dps = post_mit * measured`,
which is per-cast combat damage multiplied by a whole-game-including-death-time
cast frequency. The two factors are on different clocks.

## SUB-QUESTION 2 - DOUBLE-COUNT (this is what kills Shape C)

**Does the measured rate already embed the population's average haste? No, not
recoverably.** This is the load-bearing premise of my assigned shape, and it
fails measurement.

`participants` carries `item0..item6` (0 NULL rows, 75 of 30562 with the first
three empty), so per-match final builds ARE available. I summed item ability
haste per row via `agents/daemon_slayer/_item_ability_haste.py` (220 items) and
regressed casts/sec on it, within champion, on SR queues (6620 rows).

The naive correlation looks supportive - and is a confound. Item AH is a proxy
for game length: **r(item_ah, game_duration) = 0.392** pooled. Longer game, more
gold, more items, more haste.

Controlling for duration by stratification (within a game-length band, top AH
third vs bottom AH third, champion-normalised), the **elasticity** - observed
rate response divided by the response the cooldown formula predicts - is:

| duration band (s) | n | AH lo -> hi | theoretical ratio | observed ratio | ELASTICITY |
|---|---|---|---|---|---|
| 60-1200 | 1200 | 0 -> 25 | 1.250 | 1.087 | 0.348 |
| 1200-1500 | 1370 | 0 -> 35 | 1.350 | 1.007 | **0.019** |
| 1500-1800 | 1820 | 0 -> 40 | 1.400 | 1.034 | **0.085** |
| 1800-2100 | 1360 | 0 -> 45 | 1.450 | 1.028 | **0.063** |
| 2100+ | 870 | 0 -> 50 | 1.500 | 1.013 | **0.026** |

**Median elasticity across bands: 0.063.** Within a fixed game length, going
from 0 to 40-50 ability haste delivers about 6% of the cast-rate increase the
cooldown formula predicts. Pooled partial correlations agree:
`partial(ah, rate | duration)` = 0.180 / 0.168 / 0.159 / 0.165 for Q/W/E/R
(n=6582), down from raw 0.252 / 0.256 / 0.265 / 0.337 once duration is removed.

This is an **independent confirmation of the slack result** by a completely
different method on different data. Slack says ~94% of pairs have no cooldown
headroom to convert; elasticity says the conversion empirically does not happen.
Two methods, one conclusion.

There is no meaningful double-count to correct. **Shape C is a fix for a bias I
measured and could not find.** Applying a delta multiplier on top of the measured
rate would not remove an embedded haste effect - it would inject an effect the
population data says is not there.

## SUB-QUESTION 3 - COUNTERFACTUAL (fatal, and independently so)

**Yes, fatal.** A build ranker asks "what happens if I buy THIS item." A
population median cannot answer a counterfactual about a build it never
observed, and at this sample size it cannot answer one about builds it did
observe either.

Per-champion SR sample counts: **Aatrox 36, Ambessa 48, median champion 32.**
Shape C needs to estimate, per champion, both a baseline haste and the response
slope around it, from ~36 rows in which the regressor is confounded with game
duration at r=0.392.

My own per-champion, per-band elasticity estimates:

```
Aatrox   1500-1800  n=12  ah 10->30  elast= -0.45
Aatrox   1800-2100  n=10  ah 10->50  elast= +0.38
Ambessa    60-1200  n= 9  ah  0->15  elast= +0.82
Ambessa  1500-1800  n=14  ah 12->40  elast= +0.11
Ambessa  1800-2100  n=14  ah 22->50  elast= +0.05
Ambessa  2100+      n= 6  ah 25->58  elast= +1.23
```

Adjacent bands of the **same champion** disagree by more than the entire
plausible range of the parameter (-0.45 to +1.23). That is an estimator with no
power. A per-champion baseline computed from this would be noise, and Shape C
would multiply the ranking by that noise.

Note the sign on the anchor: **Aatrox's duration-controlled partial correlation
between item haste and Q rate is NEGATIVE, -0.108.** His high-haste quartile
casts Q at 0.1023/s versus 0.1055/s for his low-haste quartile - slower, with
five times the haste (10 -> 50 AH), because the high-haste games are longer
(1612s -> 1929s median). Viktor shows the same inversion (0.0535 -> 0.0488).

For the anchor champion of "the largest family in the sweep", the data points
the wrong way.

## SUB-QUESTION 4 - WHAT ACTUALLY EXISTS (established before proposing)

Verified live, this session, against current line numbers:

- **`dps.py` has NO ability model at all.** `grep -c "ability_haste" dps.py`
  returns **0**. Its one per-second quantity is
  `dps.py:1023`: `ult_casts_per_sec = get_ult_casts_per_sec(resolved.champion_name, mode)`
  - the same empirical median, so scaling it by haste inherits every defect
  above.
- **`hybrid.py:73-79` `_damage_axis`** returns `"ap"` only when
  `info.magic > info.attack`.
- **`hybrid.py:462`** routes the AP axis to `_ability_damage` (-> `compute_ability_dps`).
- **`hybrid.py:468`** is the AD branch: `base_damage = dps_result.weighted_dps`.

Resolved live from the snapshot:

```
Aatrox    attack=8  magic=3  -> AXIS=ad
Ambessa   attack=9  magic=0  -> AXIS=ad
```

**Both anchors take `hybrid.py:468`.** Their damage score is auto-attack DPS
from `dps.py`. The seam this work item targets (`ability_dps.py:1252-1261`) is
**not on their scoring path at all.**

The haste-shortened cooldown is computed at `ability_dps.py:1114` and then
discarded: `ability_dps.py:1252-1253` takes `measured` and labels it
`"measured"`; the cooldown is consumed only inside the `measured <= 0` fallback
at `:1255-1259`. Verified live - adding an AH item to an Aatrox build leaves
`eff_cd` at 4.62s and `cps` at 0.10108 unchanged, bit for bit.

---

## THE FOUR KILLS OF SHAPE C

1. **The double-count premise is false.** Duration-stratified elasticity 0.063.
   There is no embedded haste effect to correct.
2. **The baseline is unestimable.** Aatrox n=36; same-champion adjacent-band
   estimates span -0.45 to +1.23.
3. **The seam is not on the anchors' path.** Aatrox and Ambessa route AD
   (`hybrid.py:468`) to a scorer with zero ability model.
4. **The item RM-39 names carries no haste the engine can see.** See below.

### Kill 4 in detail - the premise of the work item is wrong on this patch

RM-39's evidence is "his #1 real item Spear of Shojin sits rank 51/143" and the
prescription is "credit ABILITY HASTE." DDragon 16.14.1 for item `3161`:

```
45 Attack Damage
450 Health
Dragonforce: Gain 25 Basic Ability Haste.
Focused Will: Dealing damage with Abilities increases your Champion's Ability
and Passive damage by 3% for 6 seconds (stacks 4 times).
```

Shojin's 25 Basic Ability Haste lives in the **passive text**, not the `<stats>`
block. `_item_ability_haste.py:29-36` documents the parse rule: only the FIRST
`<stats>` block is read, and "conditional / passive-granted AH is invisible to
the checker by design." Confirmed live: `_ITEM_ABILITY_HASTE` has **no entry for
3161**, and `total_item_ability_haste(["6698","3071","3053"])` returns 30.0
whether or not Shojin is appended.

**Every haste shape - mine and the three being argued in parallel - multiplies
by a Shojin haste delta of exactly zero.** No haste term of any design can move
Spear of Shojin one rank until that registry gap is closed. The rule is
defensible for genuinely conditional grants; Shojin's "Gain 25 Basic Ability
Haste" is unconditional and merely formatted as a named passive, so it is a
misclassification.

Reproduced live at build depth (`POST /rank-bruiser`, level 13, SR, vs
100 AR / 60 MR / 2400 HP, base `["6698","3071","3053"]`, `top=200`), so this is
not the `item_ids=[]` artifact:

| champion | BotRK | Spear of Shojin |
|---|---|---|
| Aatrox (depth 3) | #2, dDPS 72.99 | **#44**, dDPS 11.46, dEHP 1242.0 |
| Aatrox (empty) | #1, dDPS 60.16 | #44, dDPS 9.74 |
| Ambessa (depth 3) | **#1**, dDPS 142.52 | **#40**, dDPS 22.94, dEHP 1235.2 |

Shojin's credited damage is its 45 AD converted to auto-attack DPS, nothing
else. Its 450 HP IS credited (dEHP ~1240). What is missing is its **ability**
value.

---

## WHAT ACTUALLY BLOCKS RM-39 (the reframe)

Three blockers stacked, in the order they bind. Haste is the **last** one, and
it never binds because the two in front of it never clear.

1. **The hybrid AD branch has no ability damage term.** `hybrid.py:468` scores
   Aatrox on auto-attacks. His Q sweetspot - the primary damage in his kit -
   contributes nothing. This is why BotRK wins: the scorer is measuring the
   thing BotRK is best at and nothing else. It also explains Ambessa's
   6-core-item whitelist result exactly: among six items, the one with the least
   auto-attack contribution ranks last. That is model-independent proof of a
   model gap - but the gap is the **missing ability term**, not a missing haste
   term.
2. **Shojin's Focused Will amp is AP-branch only and DEFAULT-OFF.**
   `ability_dps.py:1300` (`if assume_ability_amp:`) folds
   `total_ability_damage_amp` (`effects.py:502`, 3% per stack x 4 = 12%),
   modelled correctly at `_effects_data.py:698`. Aatrox never reaches it.
3. **Shojin's 25 Basic Ability Haste is absent from the registry** (kill 4).

Measured size of blocker 1, running `compute_ability_dps` on the AD anchors to
see what the AD branch discards (level 13, 3-item build):

```
Aatrox    base ability DPS = 35.23   (+Shojin -> 39.77, +4.54)
Ambessa   base ability DPS = 27.23   (+Shojin -> 29.98, +2.75)
```

Roughly 35 and 27 DPS of modelled, computable ability damage that
`hybrid.py:468` throws away on every candidate. Note the ROADMAP entry for RM-39
already leads with the correct half - "MODEL the Q sweetspot as primary AD-axis
damage" - and the haste clause is the tail. **The tail is inert; the head is the
work.**

### Scope of any honest haste term

The 38 of 676 pairs with slack < 1.5 are the only place haste could pay, and
most of that set is spurious. Inspecting the extreme tail:

```
Ivern  R slack=0.12   Shaco R slack=0.23   Zyra W slack=0.36
Riven  Q slack=0.50   Ahri  R slack=0.56   Aphelios Q slack=0.54
```

Every one is a **multi-cast, recast, or charge mechanic** where `spellN_casts`
counts several casts per activation while the model holds one activation
cooldown. These are data-shape mismatches, not cooldown-binding. The genuinely
cooldown-bound population is therefore **smaller than 5.6%**, and neither anchor
is in it (Aatrox min slack 2.14x, Ambessa min 1.59x).

---

## IF SOMEONE BUILDS IT ANYWAY - the shape, seam, and flag

Recorded so the judges can compare like for like. I do **not** recommend
building this.

- **Model shape:** `cps_effective = cps_measured * clamp(((1 + ah_build/100) /
  (1 + ah_baseline/100)) ** eta, 1.0, CAP)` where `ah_baseline` is the champion's
  median item AH from `rewind_history.db` and `eta` is the elasticity. My
  measurement puts **eta = 0.063**, i.e. the correct calibration of this model is
  "almost exactly the identity." A shape whose honest parameter is ~0 is not a
  model, it is a rounding error with a config knob.
- **Exact seam (verified this session):** `agents/daemon_slayer/ability_dps.py:1252-1261`.
  Line 1252 is `measured = get_spell_casts_per_sec(...)`; 1253 sets
  `cps_source = "measured"`; 1255 opens the `if measured <= 0:` fallback; 1261 is
  `dps = post_mit * measured`. The multiplier would land between 1259 and 1261.
  The prior LEDGER citation of `ability_dps.py:1231-1234` for this fallback has
  rotted; 1252-1261 is current at 1.221.0.
- **DEFAULT-OFF flag name:** `apply_haste_baseline_delta`, module-level in
  `ability_dps.py` with a per-call kwarg override, mirroring the shipped
  `apply_canonical_cast_rate_keys` pattern at `ult_rates.py:80`.
- **Baseline data file:** `data/daemon_slayer/champion_haste_baseline.json`,
  built by a new `scripts/build_haste_baselines.py` alongside
  `build_spell_cast_rates.py`.

**What would change in ranking if built: nothing for RM-39 or RM-43.** Probed,
not assumed. Aatrox and Ambessa route AD (`hybrid.py:468`) and never execute
line 1261. Even routed to the ability scorer, Shojin's registry haste delta is
0.0, so the multiplier is exactly 1.000 on the item the work item is about. At
eta = 0.063 the largest realistic effect anywhere on the roster - a 50 AH swing
on an AP champion who does reach the seam - is a factor of 1.026, well inside
the reordering threshold for adjacent items.

## COST ESTIMATE (honest)

**Shape C as scoped: 2 to 3 Tier-2 sessions, for a measured zero.** Baseline
extraction script and data file (~0.5), the seam plus flag plus byte-identity
proof at the default (~0.5), full dual suite and Share mirror and ENGINE bump
(~0.5), and 1 to 1.5 sessions of calibration argument over an eta whose measured
value is 0.063 with a per-champion standard error larger than the parameter.

**The reframed work is larger and worth costing separately:** giving the hybrid
AD branch an ability damage term is a genuine Tier-2 scorer change touching
`hybrid.py:462-468`, the AD/AP axis contract, every bruiser regression baseline,
and the `assume_ability_amp` default. Estimate **3 to 5 sessions**, and it
should be specified on its own evidence, not smuggled in under a haste flag.

**Cheap, separable, and independently correct: the Shojin registry gap.** Adding
`"3161": 25.0` to `_item_ability_haste.py` - and auditing the other 705 items
for unconditional passive-granted AH excluded by the same `<stats>`-only parse
rule - is Tier-2 but small (~0.5 to 1 session). It is correct regardless of which
haste shape wins, and no haste shape can demonstrate anything until it lands. It
is also currently mis-scoped as a parse-rule design choice when for unconditional
grants it is a defect.

## STRONGEST ARGUMENT AGAINST MY OWN POSITION

Steelmanning the shape I was assigned, as honestly as I can:

**The strongest objection is that I validated the measured rate against itself.**
Every number above - slack, elasticity, baseline - is computed from the same
whole-game-average statistic I am arguing is the wrong quantity. If the measured
rate is the wrong denominator (and sub-question 1 shows it is), then "haste does
not move the measured rate" may be a fact about the *statistic*, not about the
*game*. In real combat, haste unambiguously produces more casts; the League
cooldown formula is exact. My finding could be restated as "a whole-game average
is too noisy and too diluted to detect a real effect" rather than "the effect is
absent." Those are different claims, and my evidence cannot fully separate them.

I think this objection is correct in principle and still does not save Shape C -
because it is an argument for **replacing** the measured rate with an in-combat
rate, not for multiplying it by a haste delta. If the denominator is wrong, the
fix is a better denominator; layering a haste correction on a diluted statistic
compounds two errors. And it cannot rescue the shape's own premise: Shape C
exists specifically to remove an embedded population-haste bias, and if the
statistic is too diluted to show haste, it is equally too diluted to have
embedded it.

The objection does point at the one genuinely promising direction in this space:
`participants.challenges_json` and `timeline_frames` may support an
**in-combat** cast rate (casts per second alive, or per second within N seconds
of damage taken/dealt). That would be a better denominator, would make the DPS
term dimensionally coherent, and would be the honest prerequisite to revisiting
haste at all. I did not size it; it deserves its own spec.

A second, weaker objection: my elasticity is measured on *item* haste only. Rune
haste (Transcendence, the offense shard) and level-scaled cooldowns are
uncontrolled, and `perks_json` / `stat_perk_offense` are available to control
them. That would sharpen the estimate. It would not plausibly move 0.063 to
anywhere near 1.0, and it cannot touch kills 2, 3, or 4.

## WHAT KILLED IT - one line

The measured cast rate is opportunity-bound, not cooldown-bound (median slack
3.44x, elasticity 0.063), the anchors do not execute the seam (`hybrid.py:468`),
and Spear of Shojin contributes zero registry haste - so a baseline-delta
multiplier is exactly 1.000 on the item the work item was opened to fix.

## REPRODUCTION

Probe scripts are in the session scratchpad (read-only, no repo writes):
`probe_haste_baseline.py` (correlations, partials), `probe_elasticity.py`
(duration-stratified elasticity), `probe_decompose.py` (AD-branch discard),
`probe_slack.py` (roster-wide slack). All read `data/rewind_history.db` and the
live `DataSnapshot` at patch 16.14.1.
