# SPEC RM-39 / RM-43 - ability haste in the bruiser DPS term - ADJUDICATION

**VERDICT: BUILD_DIFFERENT_THING.**

Do not build any of shapes A, B, C or D. All four authors refuted their own
assigned shape with data, and they were right to. The haste model is not the
defect. Build the registry fix (small, certain, correct regardless of any haste
model) and then specify the AD-axis ability term on its own evidence. Rewrite
RM-39 and RM-43 to describe the real defect.

Adjudicated 2026-07-18. ENGINE 1.221.0, patch 16.14.1, DS live on `:8893`
(`/health` probed this run). Every file:line below re-verified this run by
reading the file. No production code written.

---

## CORRECTION OF RECORD - 2026-07-18, same day, post-adjudication

**One claim in this document is WRONG and is retracted: that the RM-39/RM-43
premise "does not reproduce".** It reproduces exactly. Every statement below of
the form "BotRK measures #52-57, not #1" or "Trinity Force is #1" is an artifact
of probing against the route's DEFAULT target, which is `target_armor=0.0,
target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0`. BotRK's on-hit damage is
a percentage of target MAX HP, so against a 0-HP target it contributes ~nothing
and sinks ~50 places. The original sweep probed `armor 100 / mr 60 / hp 2500 /
bonus 1200`, which the adjudication did not carry over.

Re-probed at those original targets, ENGINE 1.221.0, `/rank-bruiser`, L16, SR,
top=200:

| champion | ROADMAP claim | measured | verdict |
|---|---|---|---|
| Aatrox | BotRK #1, Shojin 51 | BotRK **#1**, Shojin **51** | exact match |
| Ambessa | BotRK #1, Shojin 47 | BotRK **#1**, Shojin **47** | exact match |

**The VERDICT and the answer to the blocking question are UNCHANGED, and are now
stronger** - they rest on code structure and call-counting, not on that probe.
Re-verified at the corrected tanky targets through the production route
`server._route_rank_bruiser`, with `compute_ability_dps` wrapped in a counter
(patched in BOTH `ability_dps` and `hybrid`, which imports it by name):

    Aatrox   TANKY  n=140  compute_ability_dps CALLS=0   BotRK=1  Shojin=51
    Ambessa  TANKY  n=140  compute_ability_dps CALLS=0   BotRK=1  Shojin=47
    Veigar   /rank-mage    compute_ability_dps CALLS=142          (control)

So the defect is real and exactly as RM-39 describes it, AND ability haste is
inert for it - the ability-DPS path is never entered for these champions at the
very target conditions where the defect appears. Sections 2-6 stand. Only the
"premise does not reproduce" thread is retracted.

Consequence for RM-39/RM-43: they should be **re-scoped, not rewritten**. The
observed defect stays as written; only the named MECHANISM (ability haste)
changes to the missing AD-axis ability term. New probe trap recorded in
[[reference_ds_probe_zero_target_defaults]].

---

## 1. THE BLOCKING QUESTION

> Should ability haste modulate a MEASURED cast rate at all?

### ANSWER: NO. Not under any of the four shapes, and not while the measured rate keeps its current definition.

This is not a hedge and not an averaging of the four positions. Three
independent disqualifiers, each verified against the code this run, each
individually sufficient. Design B argued a conditional YES; B is overruled, and
section 1.4 says exactly why.

### 1.1 It cannot answer a counterfactual (structural)

`ult_rates.py:201-206` - the lookup takes **no `item_ids`**:

```python
def get_spell_casts_per_sec(
    champion_name: str,
    key: str,
    mode: str,
    apply_canonical_cast_rate_keys: bool | None = None,
) -> float:
```

The measured rate is therefore mathematically constant across every candidate
in a rank. `dps = post_mit * measured` (`ability_dps.py:1261`) has a nonzero
derivative with respect to AD/AP items through `post_mit`, and an **exactly
zero** derivative with respect to every cooldown and haste item in the game. A
build ranker exists to answer "what changes if I buy this". This term
constitutionally cannot.

### 1.2 It is the wrong quantity (dimensional)

Verified at the generator, not inferred. `scripts/build_spell_cast_rates.py:128-131`:

```python
"Q": (q_casts or 0) / dur,
```

where `dur` is `m.game_duration_s`, selected at `:105-110` and gated only by
`AND m.game_duration_s > 60` at `:112`. `ult_rates.py:14-15` states the same
contract. The denominator is **whole-game wall clock** - laning, walking,
recalling, shopping, time spent dead, and the entire pre-level-6 window in which
the ultimate cannot be cast at all.

That is an engagement-frequency statistic. Putting it in a per-second combat DPS
term is already a category error. Multiplying it by a build-derived cooldown
ratio does not repair the category - it multiplies an OBSERVATION of a population
that already built whatever haste it built by a COUNTERFACTUAL about a build that
population may never have run. The product of an observation and a counterfactual
is neither.

Design C measured the consequence directly: median cooldown slack `(1/eff_cd) /
measured` is **3.44x** across all 676 measured (champion, spell) pairs, with only
**5.6%** cooldown-bound at slack < 1.5. Aatrox Q comes off cooldown every 4.62s
and is cast once every 9.89s. Shortening a cooldown that is idle 53-71% of the
time cannot manufacture casts. The binding constraint is opportunity, not
cooldown.

### 1.3 It is moot for the two champions the work item names (fatal)

`hybrid.py:73-79` classifies the damage axis from DDragon `info`:

```python
def _damage_axis(snapshot: DataSnapshot, champion_id: str) -> str:
    """Return ``"ap"`` when the champion is magic-primary, else ``"ad"``."""
    rec = snapshot.champions.get(str(champion_id)) or {}
    info = rec.get("info") or {}
    attack = int(info.get("attack", 0) or 0)
    magic = int(info.get("magic", 0) or 0)
    return "ap" if magic > attack else "ad"
```

Resolved from `data/meta_build/ddragon/16.14.1/champion.json` this run:

```
Aatrox        attack 8  magic 3  -> axis ad
Ambessa       attack 9  magic 0  -> axis ad
Mordekaiser   attack 4  magic 7  -> axis ap
Veigar        attack 2  magic 10 -> axis ap
ad-axis count: 92 of 173
```

All three `_ability_damage` call sites are gated on the `ap` branch -
`hybrid.py:462`, `hybrid.py:944`, `hybrid.py:1032`. The AD branch binds
`base_damage = dps_result.weighted_dps` (`hybrid.py:468`), whose own module
docstring says so outright (`dps.py:34`): "Ability damage is **not** included".

Confirmed by grep this run - `ability_haste` occurrences per file:

```
ability_dps.py: 33
dps.py:          0
hybrid.py:       0
```

`compute_ability_dps` is the only scoring function that reads ability haste, and
it is unreachable for both anchors. Design A proved this from the outside by
multiplying the entire ability-DPS return by 1e6 and observing byte-identical
Aatrox and Ambessa rankings while the Veigar control moved 4,037 -> 28,279,380.
That is the single cleanest measurement in the packet.

**The ROADMAP instruction "credit ABILITY HASTE in the hybrid DPS term" is not
well-formed.** For 92 of 173 champions there is no ability term in that branch to
credit haste into.

### 1.4 Why Design B's conditional YES is overruled

B is the only design that identified AND structurally corrected the
double-count. `rate * (cd(pop_ah) / cd(build_ah))` prices only the haste delta
over the population the observation came from; that is the textbook-correct move
for converting an observational statistic into a counterfactual one, and it is
why B's baseline barely moves (26.37 -> 24.88) where the naive multiplier
inflates +142%. B earned its finding honestly with a 2x2 that showed a real
interaction. It is still overruled, for three reasons:

1. **It corrects the wrong base.** Renormalizing a diluted whole-game average
   leaves a diluted whole-game average. If the denominator is wrong, the fix is a
   better denominator, not a correction factor layered on top.
2. **Its own damping sweep kills its headline.** B's top-3 Shojin result exists
   ONLY at elasticity `e = 1.0`. B's own ratio table says 0.485 for Aatrox Q. At
   the measured elasticity the result is 6/13 and 4/13, not 3/13. The program is
   parameter-dependent on a free parameter nobody has measured.
3. **`pop_ah` is confounded.** It is drawn from the same games as the rate, and C
   measured item AH against game duration at **r = 0.392**. The divisor silently
   attributes a longer-game association to cooldowns. C also found the sign
   inverts on the anchor: Aatrox's high-haste quartile casts Q *slower*
   (0.1023/s) than his low-haste quartile (0.1055/s).

C named the epistemic trap that governs all of this and then correctly refused to
let it rescue its own shape: every number in this packet was computed from the
statistic being argued invalid, so "haste does not move the rate" may be a fact
about the statistic rather than about the game - but a statistic too diluted to
SHOW haste is equally too diluted to have EMBEDDED the population-haste bias that
B and C both exist to remove. That argument is correct and it is decisive.

### 1.5 The one honest path to a YES, later

The question becomes well-posed only after the measured rate is replaced, not
corrected: an **in-combat cast rate** (casts per second alive, or per second
within N seconds of damage dealt or taken) from `participants.challenges_json`
plus `timeline_frames`, with the measured rate demoted from a DPS multiplier to a
cast-propensity prior. A, C and D independently converged on this and none of
them sized it. It is a separate spec. Note the signal that must not be discarded
on the way: Aatrox W sits at 17.6% of theoretical because Infernal Chains is a
utility spell genuinely cast less often than available. A pure cooldown-inverse
model throws that away and will over-credit low-utility spells.

---

## 2. WHAT TO BUILD INSTEAD

### 2.1 FIRST - register unconditional passive-granted ability haste (SIX ids, not one or two)

I swept every 16.14.1 item whose description mentions Ability Haste against
`_ITEM_ABILITY_HASTE` this run, filtered to `purchasable` on map 11 or map 30,
excluding items whose leading `<stats>` block already carries AH. **Both B and D
undercounted this and their cost estimates rest on the undercount.** The affected
set:

| id | name | map | grant |
|---|---|---|---|
| 3161 | Spear of Shojin | 11 | Dragonforce: 25 **Basic** Ability Haste |
| 223161 | Spear of Shojin (Arena mirror) | 30 | Dragonforce: 25 **Basic** Ability Haste |
| 3073 | Experimental Hexplate | 11 | Hexcharged: 30 **Ultimate** Ability Haste |
| 223073 | Experimental Hexplate (Arena mirror) | 30 | Hexcharged: 30 **Ultimate** Ability Haste |
| 2512 | Fiendhunter Bolts | 11 | Night Vigil: 30 **Ultimate** Ability Haste |
| 222512 | Fiendhunter Bolts (Arena mirror) | 30 | Night Vigil: 30 **Ultimate** Ability Haste |

**Leave 2517 / 222517 Endless Hunger alone.** "Famine: Gain Ability Haste based
on your Bonus AD" is genuinely conditional and the existing exclusion is correct
there. Swarm (map 33) evolve items are out of scope.

This is a **schema lift, not a data patch.** `_ITEM_ABILITY_HASTE` is
`dict[str, float]` - a flat scalar per item - but these grants are TYPED (Basic
applies to Q/W/E, Ultimate applies to R only). `ability_dps.py:1112` states the
current contract explicitly: "Single haste-total applies uniformly to all 4 spell
keys (Q/W/E/R) at the engine layer". Pinning 25.0 flat for Shojin over-credits R;
pinning 30.0 flat for Hexplate and Fiendhunter over-credits Q/W/E. Decide the
typed-value lift explicitly rather than by default. A drift-checker exemption is
also required, because `_item_ability_haste.py:29-36` documents that non-`<stats>`
AH is invisible to `ops/audit/item_ah_drift_check.py` **by design** - this is a
misclassification of an unconditional grant, not a parse bug.

Estimate 1 to 1.5 sessions, Tier-2. **It produces ZERO live ranking change for
the anchors on its own** (Design D's ablation row C: Aatrox #40 -> #40, Ambessa
#37 -> #37). Ship it because it is correct and because it is a hard prerequisite
for ever demonstrating any haste model - today every shape in this packet
multiplies by a Shojin delta of exactly 0.0 - but do NOT log it as RM-39
progress. B is right that sequencing the cheap half first and declaring progress
would be a false positive.

### 2.2 SECOND - the real defect: the missing ability term on the AD branch

`hybrid.py:462-468` and its ranker mirrors at `:944` and `:1032`. 92 of 173
champions are scored on auto-attack DPS only. The anchors' real ability DPS
(roughly 27-35 for Aatrox, 22-27 for Ambessa, depending on the probe build) is
computed nowhere and discarded structurally. This is what RM-39 and RM-43 are
actually about.

Non-negotiable conditions on this work:

- **A damage-type guard is mandatory.** D's ablation row B showed that adding an
  unfiltered ability term under the current measured rate promotes Liandry's
  Torment to #1 for Aatrox, importing AP burn items onto an AD bruiser.
- **Cohort-wide golden diff across all 92 AD-axis champions**, not a
  two-champion spot check. The blast radius is the `baseline_dps` denominator for
  every AD champion routed to `ds.hybrid`.
- **DEFAULT-OFF flag, specified on its own evidence.** Do not smuggle it in under
  a haste flag.

3 to 5 sessions, Tier-2.

### 2.3 BEFORE funding 2.2 - re-derive the premise

The RM-39 headline symptom is "BotRK #1, Shojin near-last". **It does not
reproduce.** Live `POST /rank-bruiser` this run, level 13, mode SR, `top=200`:

```
Aatrox   items=[]                    n=140  top1 3078  BotRK #57  Shojin #34  Hexplate #31
Aatrox   items=[6610,3047,6333]      n=138  top1 3078  BotRK #52  Shojin #33  Hexplate #29
Ambessa  items=[]                    n=140  top1 3078  BotRK #52  Shojin #31  Hexplate #29
Ambessa  items=[6610,3047,6333]      n=138  top1 3084  BotRK #51  Shojin #28  Hexplate #23
```

Trinity Force is #1, not Botrk. Designs B, C and D all reported BotRK #1 or #2
and Shojin #40-45; none of that reproduces at either build depth in my run. Pin
down the exact probe configuration under which RM-39 was originally written and
confirm the defect is still visible in it before spending 3 to 5 sessions. Do not
fund 2.2 against a number nobody can currently reproduce. Note that 2.2 is still
justified on structural grounds (`dps.py:34`) independent of this headline - but
the work item's stated evidence must be corrected.

### 2.4 NEW PROBE TRAP - `/rank-bruiser` ignores `item_ids`

`server.py:794` reads `items = _coerce_str_list(body.get("items"), "items")`.
There is **no `item_ids` key** on this route. A body carrying `item_ids` is
silently accepted and the build is empty - reproducing exactly the
`reference_ds_probe_empty_build_artifact` failure mode the operator already has a
memory for. The task brief that commissioned all four designs instructed
`item_ids`, so any design that followed it literally was probing an empty build.

The brief also instructed `POST /rank-hybrid`. **There is no `/rank-hybrid`
route** - `server.py:2094` maps `ds.hybrid` to `/rank-bruiser`. Design A alone
caught this; B, C and D silently used the right route anyway.

Both corrections belong in the memory file before the next DS probe session.

---

## 3. IF ANYONE REVISITS THE HASTE QUESTION - what must become true

RM-39/RM-43 as haste work is DEFERRED, not closed. It becomes live only when ALL
of the following hold. None hold today.

1. **The AD-axis ability term exists and is shipped** (2.2). Until then any haste
   model is provably inert for these two champions - measured at 1e6
   perturbation, not argued.
2. **The six passive-grant ids are registered with typed Basic/Ultimate values**
   (2.1). Until then the haste delta on the motivating item is exactly 0.0.
3. **The measured rate has been replaced by an in-combat rate**, not corrected by
   a ratio (1.5). If the denominator is wrong, layering a correction on it
   compounds two errors.
4. **The elasticity has been measured against the new rate and is near 1.0.** C
   measured 0.063 pooled against the current statistic, with the sign inverting
   on Aatrox. B's headline needs 1.0. If the honest value stays near 0.06, the
   largest realistic roster-wide effect is a factor of ~1.026 - inside the
   adjacent-item reordering threshold, which means the correction is unobservable
   and unfundable.

### Should RM-39 and RM-43 be rewritten?

**YES - rewrite both, do not close them.** The champions are correctly
identified; the mechanism named in the work item is wrong.

- Strike "credit ABILITY HASTE in the hybrid DPS term" from both. It names a term
  that does not exist for these champions.
- Retitle to the real defect: *"AD-axis hybrid champions score
  `alpha*auto_attack_dps + beta*ehp` with no ability damage term at all
  (`hybrid.py:462-468`, 92 of 173 champions)."*
- Keep the ROADMAP entry's existing first clause - "MODEL the Q sweetspot as
  primary AD-axis damage" is the correct half and already points at 2.2. The
  haste clause is the inert tail; delete it.
- Split the registry gap (2.1) into its own item. It is independently correct,
  independently verifiable, and must not be bundled under a haste banner.
- Correct the cited evidence per 2.3 or replace it with the structural argument.

---

## 4. REJECTED SHAPES - one line each

| Shape | Reason it lost |
|---|---|
| **A** - haste-scaled theoretical blended with measured | Keeps the wrong quantity as a permanent load-bearing prior; a per-spell blend weight is 4 x 173 = 692 free parameters fit against a statistic already established as the wrong one, laundering the bias into the engine. A's own measured/theoretical spread (Aatrox Q 41.8 / W 17.6 / E 39.0 / R 34.3, a 3.2x range inside one champion) proves a per-champion `w` is too coarse. |
| **B** - relative correction `rate * cd(pop_ah)/cd(build_ah)` | Structurally the best haste shape and still overruled: it corrects the wrong base, its top-3 headline exists only at elasticity 1.0 which its own ratio table contradicts at 0.485, and `pop_ah` is confounded with game duration at r = 0.392. |
| **C** - baseline-relative haste delta | Self-refuted four ways; it is a correction for a population-haste bias that C went looking for in the source data and could not find. Best measurement work in the packet, dead shape. |
| **D** - cooldown-bound in-combat rate | Right diagnosis, wrong prescription. The stable variant `(1 + T/eff_cd)/T = 1/T + 1/eff_cd` converges to `1/eff_cd`, so the honest form contains no fight model at all - it is `theoretical` at `ability_dps.py:1256`, already written. Its own ablation shows an indiscriminate class reweight (items WITH haste move a median +10 ranks up, n=55; without, -6, n=80; Axiom Arc #48 -> #18 on Aatrox). The discrete form swings Shojin 56 places between T=5 and T=10. |

### Factual errors found in the designs (verified this run)

- **A is wrong on mechanism.** A says Shojin "is registered at 0.0 ability haste
  ... because DDragon stats omits AH and Meraki has abilityHaste:null". It is
  **absent from the registry entirely** - `'3161' in _ITEM_ABILITY_HASTE` is
  `False`, as are `223161`, `3073`, `223073`, `2512`, `222512`, `2517`. B, C and
  D have the correct mechanism. A's conclusion (delta 0.0) survives; the fix
  shape does not follow from A's premise.
- **B is wrong on scope.** "Exactly ONE base SR item is missing" is false. Three
  base SR items are missing (3161, 3073, 2512), plus three Arena mirrors. B's
  "small, certain, pinpoint" framing of the registry fix does not hold.
- **D is wrong on scope.** "Exactly 2 items in this class: 3161 and Arena mirror
  223161" is false by the same sweep. D's "2 registry lines, 0.5 session" cost
  rests directly on this undercount.
- **B, C and D do not reproduce on the BotRK headline** - see 2.3.
- **C's registry claim is the only one that survives audit intact**, precisely
  because C made the weaker correct claim ("audit the other 705 items for
  unconditional passive-granted AH caught by the same `<stats>`-only rule")
  rather than asserting a count.
- **The Lens 2 judge was right** on the sweep and is confirmed: 3073 and 2512 are
  purchasable map-11 items with base ids distinct from their 22xxxx mirrors.
- **Not a design error:** A's "4 of 173 champions have info.attack/magic both
  zero" is correct - Akshan, Rell, Seraphine, Vex. The in-repo comment at
  `hybrid.py:69-71` lists five including Qiyana and is **stale**. Worth a
  one-line cleanup when that file is next touched.

---

## 5. CITATIONS

Every line below read this run at ENGINE 1.221.0 / patch 16.14.1.

| file:line | quoted text | what it establishes |
|---|---|---|
| `agents/daemon_slayer/ult_rates.py:201-206` | `def get_spell_casts_per_sec(champion_name: str, key: str, mode: str, apply_canonical_cast_rate_keys: bool \| None = None) -> float:` | No `item_ids` param - the term is constant across candidates; zero derivative w.r.t. every item. |
| `agents/daemon_slayer/ult_rates.py:14-15` | `Both files are derived from ``rewind_history.db.participants.spell[1-4]_casts / matches.game_duration_s``` | Provenance: whole-game denominator. |
| `scripts/build_spell_cast_rates.py:112` | `AND m.game_duration_s > 60` | The only duration gate. |
| `scripts/build_spell_cast_rates.py:128-131` | `"Q": (q_casts or 0) / dur,` | Casts divided by whole-game duration - engagement frequency, not a combat rate. |
| `agents/daemon_slayer/ability_dps.py:1252` | `measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)` | The assigned seam. LEDGER's `:1231` and the brief's `:1253` have both rotted. |
| `agents/daemon_slayer/ability_dps.py:1253` | `cps_source = "measured"` | Default path. |
| `agents/daemon_slayer/ability_dps.py:1256` | `theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0` | The haste-shortened rate exists but is reachable only inside the dead `measured <= 0` branch. |
| `agents/daemon_slayer/ability_dps.py:1261` | `dps = post_mit * measured` | Nonzero derivative w.r.t. AD/AP via `post_mit`; exactly zero w.r.t. all haste items. |
| `agents/daemon_slayer/ability_dps.py:1113` | `base_ah = total_item_ability_haste(resolved.item_ids)` | The only scoring consumer of item AH. |
| `agents/daemon_slayer/ability_dps.py:1112` | `haste-total applies uniformly to all 4 spell keys (Q/W/E/R) at the engine layer` | Why Basic-vs-Ultimate grants need a schema lift, not a scalar pin. |
| `agents/daemon_slayer/hybrid.py:73-79` | `return "ap" if magic > attack else "ad"` | Axis classifier. Aatrox 8/3 -> ad; Ambessa 9/0 -> ad. |
| `agents/daemon_slayer/hybrid.py:462` | `if _damage_axis(snapshot, champion_id) == "ap":` | Ability damage gated to AP. |
| `agents/daemon_slayer/hybrid.py:468` | `base_damage = dps_result.weighted_dps` | Where both anchors land - auto-attack only. |
| `agents/daemon_slayer/hybrid.py:944` | `if axis == "ap"` | Ranker baseline mirror of the same gate. |
| `agents/daemon_slayer/hybrid.py:1032` | `if axis == "ap"` | Ranker scored-candidate mirror. |
| `agents/daemon_slayer/hybrid.py:69-71` | `the few champs DDragon leaves zeroed (Seraphine / Akshan / Rell / Vex / Qiyana)` | STALE - actual zeroed set is 4 (Akshan, Rell, Seraphine, Vex). |
| `agents/daemon_slayer/dps.py:34` | `Ability damage is **not** included - spell formulas aren't in the snapshot.` | The AD branch is auto-attack-only by design and says so. |
| `agents/daemon_slayer/dps.py` (grep) | `ability_haste` count = 0 | The AD scorer cannot read haste at all. |
| `agents/daemon_slayer/hybrid.py` (grep) | `ability_haste` count = 0 | Same. |
| `agents/daemon_slayer/_item_ability_haste.py:29-36` | `conditional / passive-granted AH is invisible to the checker by design` | The exclusion is deliberate; unconditional grants are a misclassification. |
| `agents/daemon_slayer/_item_ability_haste.py` (probe) | `'3161' in _ITEM_ABILITY_HASTE -> False`; `total_item_ability_haste(['3161']) -> 0.0` | Shojin absent, not registered at 0.0. Refutes Design A's mechanism. |
| `data/meta_build/ddragon/16.14.1/item.json` (sweep) | 3161 / 223161 / 3073 / 223073 / 2512 / 222512 unregistered with unconditional passive AH; 2517 conditional | Six ids, not one (B) or two (D). |
| `data/meta_build/ddragon/16.14.1/champion.json` | Aatrox `attack 8 magic 3`; Ambessa `attack 9 magic 0`; 92 of 173 resolve `ad` | Blast radius of the real fix. |
| `agents/daemon_slayer/server.py:794` | `items = _coerce_str_list(body.get("items"), "items")` | `/rank-bruiser` reads `items`, NOT `item_ids`. New probe trap. |
| `agents/daemon_slayer/server.py:2094` | `"/rank-bruiser": _route_rank_bruiser,` | No `/rank-hybrid` route exists. |
| `http://127.0.0.1:8893/health` | `{"status": "ok", "engine_version": "1.221.0", "patch": "16.14.1", "champions": 173, "items": 706}` | Live engine identity for every probe above. |

---

## 6. TIER-2 TAIL - not applicable

No engine change is authorized by this document, so no ENGINE bump, no HZ-B1 /
HZ-B2 regen, no Share mirror sync, no `:8893` restart. When 2.1 or 2.2 is
scheduled, each carries its own full Tier-2 tail (ENGINE bump as a quoted
literal, `--champions all` regen of BOTH HZ-B1 and HZ-B2, Share mirror in the
SAME commit, DS `:8893` restart via `schtasks /End` + `/Run` after confirming the
port is free, then a live `/rank-bruiser` probe using `items` not `item_ids`).
