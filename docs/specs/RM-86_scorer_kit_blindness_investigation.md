# RM-86 - Is the DS scorer layer kit-blind? Investigation + spec

Status: INVESTIGATION COMPLETE - deliverable is this spec, no patch.
Date: 2026-07-18. Engine at time of measurement: 1.217.0 / patch 16.14.1 / 173 champions / 706 items.
Scope: findings (a) RM-83 Naafiri, (b) RM-85 Nasus, (c) ds.hps champion-invariance, (d) Vayne / Silver Bolts.

## 0. Verdict up front

**PARTIAL UNIFICATION. Three of the four findings share one root cause; the fourth does not.**

- (a) Naafiri, (c) ds.hps invariance and (d) Vayne all reduce to **RC-1: the ranker
  optimises a single scalar throughput objective whose champion-specific input is
  STATS ONLY, with no representation of what the kit can actually use.**
- (b) Nasus does **not**. It is **RC-2: candidate-pool partition** - a
  membership problem in the archetype pool, structurally the INVERSE of RC-1
  (too narrow a candidate set, not too permissive a ranking).

Two root causes, not one, and not four. The prior standing read is **refuted in
both directions** - see section 2.

## 1. The Vayne question, ANSWERED (finding d)

Carried unanswered across three sessions. Answered here two independent ways.

**Data layer.** `data/daemon_slayer/16.14.1/champion_abilities.json` -> `Vayne.W`
("Silver Bolts") carries exactly two blocks:

```
{"attribute": "Bonus True Damage",   "target_max_hp_pct": [6, 7, 8, 9, 10]}
{"attribute": "Minimum Bonus Damage", "base": [50, 65, 80, 95, 110]}
```

Zero AD ratio, zero AS ratio, zero AP ratio. So the STORED model of Silver Bolts
is fully stat-independent.

**Engine layer - and this is the stronger finding.** The question assumed
`ds.dps` models W *as stat-independent*. It does not model it **at all**.

- Static: `agents/daemon_slayer/dps.py` imports `data_loader`, `effects`,
  `engine.build_champion`, `stats`, `ult_rates`. It **never imports
  `abilities` / `AbilitiesSnapshot`, and the string `damage_blocks` does not
  appear in the file.** Champion abilities are not an input to `ds.dps`.
- Behavioural, live `:8893`, Vayne / carry / L16, sweeping target max HP:

  | target_max_hp | BotRK | Runaan's | Kraken | Stormrazor |
  |---|---|---|---|---|
  | 1200 | 70 | 66 | 61 | 52 |
  | 2500 | 120 | 66 | 61 | 52 |
  | 5000 | 217 | 66 | 61 | 52 |

  Only BotRK responds, because BotRK carries its OWN `%maxHP` on-hit term. If
  Silver Bolts were modelled, every attack-speed item would scale with target HP
  (more autos -> more third-hit procs) and the whole column would move. It is
  flat.

**Consequence.** Tank Vayne is unrepresentable, and for a stronger reason than
the question supposed: her single largest damage source against high-HP targets
is invisible to the scorer that ranks her items. No item filter can fix this -
the objective function does not contain the term. This is the same shape as (c):
a scorer that cannot represent the kit it is scoring for.

**Do not carry this question a fourth time. It is closed.**

## 2. The measurement that refutes the standing read

Standing read (2026-07-13 3-front QA, recorded in
`project_ds_build_reco_optimal_not_winrate`): *"the scorer applies the ONE
on-hit-optimal answer to EVERY AD carry, kit-blind ... Mages / tanks /
enchanters are CLEAN - fault is the AD sustained-DPS path only."*

Method: for each scorer, rank the top 10 items for 6 different champions routed
to it, all at the same target state (armor 100 / MR 60 / maxHP 2500 / bonusHP
1200) and level 16, `item_ids=[]`. Count exact top-10 order identity against the
first champion, and mean top-5 set overlap.

| route | scorer | exact-identical top10 | mean top-5 set overlap |
|---|---|---|---|
| tank | `ds.ehp` | 4 / 6 | **5.0 / 5** |
| mage | `ds.ability` | 3 / 6 | **5.0 / 5** |
| enchanter | `ds.hps` | 10 / 10 (batch16) | **5.0 / 5** |
| bruiser | `ds.hybrid` | 1 / 6 | 4.5 / 5 |
| assassin | `ds.burst` | 1 / 6 | 2.8 / 5 |
| carry | `ds.dps` | 1 / 6 | **2.2 / 5** |

Champion sets: carry = Jinx/Vayne/Caitlyn/Ezreal/Ashe/Kaisa; bruiser =
Darius/Nocturne/Nilah/Garen/Sett/Illaoi; tank = Nunu/Malphite/Ornn/Sion/Rammus/
Zac; mage = Neeko/Nunu/Morgana/Lux/Syndra/Veigar; assassin = Nidalee/Zed/Talon/
Naafiri/Katarina/Fizz.

**Both halves of the standing read are wrong.**

1. *"Mages / tanks / enchanters are CLEAN"* - **FALSE.** They are the MOST
   invariant scorers in the engine (5.0/5 overlap). Every AP champion probed
   gets `Liandry's Torment > Blackfire Torch > {Void Staff, Rabadon's} >
   Shadowflame > Mejai's`, whether or not the kit has a damage-over-time
   component at all (Syndra and Veigar have none; they still get Liandry's #1).
   Every tank probed gets `Randuin's Omen > Warmog's > Jak'Sho > Kaenic Rookern`.
2. *"fault is the AD sustained-DPS path only"* - **FALSE, and inverted.**
   `ds.dps` is the LEAST invariant scorer measured (2.2/5). It genuinely
   discriminates: Jinx/Caitlyn get crit + Lord Dominik's; Vayne/Ashe/Kaisa get
   on-hit; Ezreal gets Essence Reaver. That differentiation comes from champion
   base stats and per-level growth interacting with item stats - which is real
   kit signal, just a thin one.

Corroborating single-probe evidence gathered the same session:

- Nilah (`bruiser`) and Nocturne (`bruiser`) return the same six items in nearly
  the same order despite sharing nothing mechanically.
- Neeko (`mage`) and Nunu (`mage`) return near-identical lists.
- Morgana, Thresh, Rakan, Taric, Bard and Zilean, routed to `enchanter`, return a
  **byte-identical** top 6.
- `ds.burst` hands Nidalee - an AP jungler whose real first item is Lich Bane -
  `BotRK > Essence Reaver > Trinity Force > Infinity Edge > Lich Bane`. The AD
  template reaches an AP champion because `burst.py` sources its auto-attack
  component from `compute_dps` (`burst.py:85-88`), which is RC-1 by construction.

**Important caveat - invariance is not automatically a defect.** "Which item adds
the most effective HP" has a genuinely near-champion-invariant answer; `ds.ehp`
scoring 5.0/5 is largely CORRECT behaviour. The defect is not sameness. The
defect is sameness that produces an item the champion would never build. That
distinction is the whole spec; see section 4.

## 3. RC-1 stated precisely

> Every scorer ranks candidate items by the marginal change in ONE scalar
> objective (DPS / EHP / ability damage / heal-shield throughput), computed by a
> greedy per-slot argmax over single-item delta. The champion enters that
> objective only through **base stats and stat coefficients**. Nothing in the
> ranking path asks whether the kit can USE the stat an item provides.

Named seams, already on record and re-verified this session:

- full-catalog candidate pool whose only filter is `filter_shared_uniques`
  (`core/build_order.py:597,661,681`; `core/daemon_slayer_client.py:959`)
- no archetype-coherence gate on the ranking sort key
- `core/build_planner/kit_synergy.py` exists as the intended metric lever and is
  not consulted by the rankers

How each finding reduces:

- **(a) Naafiri / RM-83.** Every Naafiri damage block scales `bonus_ad_pct` only
  - zero AS terms, zero crit terms, and no attack-timer reset in the kit. The
  ranker cannot see that; it sees an item granting AS + on-hit `%maxHP` (BotRK)
  raising the scalar, so BotRK wins. Re-probed at four build depths in batch16;
  BotRK holds #1 and IE climbs. Voltaic Cyclosword, her 87% real first item,
  sits #15/#22.
- **(c) `ds.hps` invariance.** Same mechanism plus a closed 9-legendary pool.
  The engine DOES compute per-champion heal/shield throughput
  (`ability_hps.py:320` parses `raw_modifiers`; Soraka 10.21/s vs Morgana
  2.52/s) - but the seam that would let that weight items,
  `apply_ability_hsp_amp`, exists ONLY on `compute_hps` and is absent from
  `rank_items_by_hps` AND the dispatcher. Note the file split: the kit-aware
  compute lives in `ability_hps.py`, the ranker in `hps.py`, and `hps.py`
  imports neither `ability_hps` nor the amp. The kit is computed and then
  discarded before ranking.
- **(d) Vayne.** The strongest form: for `ds.dps`, `ds.hybrid`, `ds.ehp` and
  `ds.onhit` the kit term is not merely unweighted, it is **absent** - none of
  those four files contains `damage_blocks` or imports `abilities`. Only
  `ability_dps.py`, `ability_hps.py` and `burst.py` read the kit at all.

Scorer kit-awareness, measured by static import:

| scorer | reads `damage_blocks` | imports abilities |
|---|---|---|
| `ability_dps.py` (mage) | 11 | yes |
| `burst.py` (assassin) | 3 | yes |
| `ability_hps.py` (hps compute) | 2 | yes |
| `dps.py` (carry) | **0** | **no** |
| `hybrid.py` (bruiser) | **0** | **no** |
| `ehp.py` (tank) | **0** | **no** |
| `onhit_dps.py` (onhit) | **0** | **no** |

Note the mismatch between this table and the invariance table: `ds.ability` reads
the kit 11 times and is still 5.0/5 invariant, while `ds.dps` reads it zero times
and is 2.2/5. **Kit-awareness at the compute layer does not imply kit-awareness at
the ranking layer.** That is the precise statement of RC-1, and it is why "just
make the scorers read the kit" is not the fix.

## 4. What the engine must do differently

The anchor: *the build target is the optimal ultimate build for the live game
state, pure simulation, and it must NEVER offer an item a champion or archetype
would never build.* A GAP means the SIMULATION is incoherent with the kit - not
that the engine disagrees with the meta.

RC-1 violates the anchor in one specific way: **an item can raise the scalar
objective through a stat the kit cannot convert into output.** BotRK raises
Naafiri's modelled DPS through attack speed she has no ratio for; Liandry's
raises Syndra's modelled ability damage through a burn the kit never applies.

The fix is therefore NOT "rank by meta" (that would invert the anchor and is
explicitly out of scope - every win-rate seam stays default-OFF, and the DSP11
kit-axis gate stays as-is). The fix is to make the SIMULATION honest about
conversion:

> For each item stat, weight its marginal contribution by the kit's measured
> ability to convert that stat into output. A stat the kit has no ratio for
> converts at (near) zero and must not raise the score.

Concretely, three layers, cheapest first:

**L1 - conversion gate on the sort key (no objective change).** Reuse the
existing Slice-B precedent: `ap_ad_coherence` in `onhit_dps.py` already penalises
off-axis candidates on the SORT key while preserving raw delta on the row
(ENGINE 1.216.0, default-OFF, byte-identical at 0.0). Generalise it from an
AP/AD axis flag to a per-stat conversion vector derived from the champion's own
`damage_blocks` (does any block carry an AS term? a crit term? a DoT?).
- Blast radius: sort key only, every scorer, default-OFF flag -> byte-identical
  until flipped. Reaches (a), (c), and the `ds.ability` Liandry's-for-everyone
  case. Does NOT reach (d) - a gate cannot add a missing term.
- Risk: LOW. Proven pattern, reversible, testable per champion.

**L2 - wire the kit-aware computes into the rankers.** `rank_items_by_hps` calls
`apply_ability_hsp_amp`; `dps.py` gains an ability-damage term for AA-routed
on-hit passives the way `onhit_dps.py` already does.
- Blast radius: MOVES ENGINE OUTPUT for every enchanter (c) and for Vayne-class
  kits (d). ENGINE bump + full dual suite + Share mirror + `:8893` + build-order
  precompute regen (both tables).
- Risk: MEDIUM. This is the only path that makes tank Vayne representable.

**L3 - candidate-pool coherence.** Addresses RC-2, not RC-1. See section 5.

Sequencing recommendation: **L1 first, default-OFF, per-champion validated on
Naafiri + Syndra + Morgana; then L2 for `ds.hps` alone (smallest blast radius,
and (c) is already fully characterised); then re-measure the invariance table
before deciding whether L2-for-dps is worth it.** Do not attempt all three in one
slice - the Engine/Build Conventions rule about validating per champion rather
than with one generic shape applies with full force here, and the invariance
table in section 2 is the regression baseline.

## 5. RC-2 - why Nasus does NOT unify

Finding (b) is a different failure. Nasus's real build spans two archetype pools:
`bruiser` reaches Trinity Force and Iceborn Gauntlet but Protoplasm Harness,
Frozen Heart and Spirit Visage are **absent from its top-40 at every depth**;
`tank` reaches all three but drops Trinity Force. His real build (jungle 55.6%,
Protoplasm Harness 59.98% first) needs items from both.

This is not "the ranker scored a bad item highly". The correct items are **not in
the candidate set being ranked**. RC-1 is a scoring-permissiveness defect; RC-2 is
a pool-membership defect. They are structurally opposite, and a conversion gate
(L1) makes RC-2 slightly WORSE by further suppressing off-axis candidates that
are already unreachable.

RC-2's fix is a pool question - union the pools for dual-axis champions, or make
pool membership a per-champion property rather than a per-archetype constant.
That is its own spec; do not fold it into an RC-1 fix.

The same pool-membership class covers the SETTLED team-aura scope limit
(Locket / Knight's Vow / Zeke's / Solstice Sleigh value allies, and no scorer's
objective contains an ally term) - logged here for completeness, not re-opened.

## 6. What would REFUTE this spec

Stated so a later session can attack it cheaply:

1. If a conversion gate (L1) is built and Naafiri's BotRK **stays** #1 with the
   gate at full strength, RC-1 is mis-stated - the driver would be something
   other than unconvertible-stat credit.
2. If `rank_items_by_hps` is wired to `apply_ability_hsp_amp` (L2) and the ten
   enchanters STILL return an identical order, then (c) is a closed-pool
   artefact rather than a missing-amp artefact, and (c) leaves the RC-1 family.
3. If a champion with zero AS ratio and zero crit ratio is found whose real
   build IS BotRK-first, the anchor reading behind (a) is wrong.

## 7. Evidence index

- Invariance table: live `:8893`, 30 champion-scorer probes, main thread.
- Vayne HP sweep: live `:8893`, Vayne/carry/L16, target_max_hp 1200/2500/5000.
- Static import table: `agents/daemon_slayer/{dps,hybrid,ehp,onhit_dps,ability_dps,ability_hps,burst}.py`.
- Silver Bolts blocks: `data/daemon_slayer/16.14.1/champion_abilities.json` -> `data.Vayne.W`.
- Enchanter byte-identity: 7 champions x 3 routes, `rank_for_primary_archetype`.
- Prior verdicts reused, not re-derived: RM-83 (Naafiri), RM-85 (Nasus), the
  batch16 `ds.hps` invariance finding, memory `project_ds_hps_champion_invariant`.
