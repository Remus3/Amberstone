# RM-39 / RM-43 - Design A: haste-scaled theoretical cast rate, measured as prior

Status: **SELF-REFUTED AS SCOPED.** Salvageable only as stage 3 of a larger fix.
Author: Design-A agent, 2026-07-18. Engine 1.221.0, patch 16.14.1, DS live on :8893.
Assigned shape: keep the measured cast rate but blend it with the haste-scaled
theoretical rate inside `ability_dps.py`, so buying ability haste moves the blend.

---

## 0. Verdict first

The assigned shape cannot work for the champions it was assigned to, and this is
not a judgement call - it is measured.

**No edit confined to `ability_dps.py` can move Aatrox's or Ambessa's item ranking
by a single position.** I multiplied the entire ability-DPS return value by 1e6
(a strictly larger perturbation than any blend weight could produce) and re-ranked.
The Aatrox and Ambessa orderings were byte-identical, Shojin held rank 47 and 42,
and the top-1 score matched to six decimal places. The Veigar control, run in the
same harness, saw its top-1 score go from 4,037 to 28,279,380.

```
Sabotage: ability DPS x 1e6
Aatrox    axis=ad  ranking_identical=True   shojin_rank 47 -> 47   top1 score 5574.687245 -> 5574.687245
Ambessa   axis=ad  ranking_identical=True   shojin_rank 42 -> 42   top1 score 4298.925264 -> 4298.925264
Veigar    axis=ap  ranking_identical=False  shojin_rank 60 -> 60   top1 score 4037.392774 -> 28279380.892605
```

The cause: `compute_ability_dps` is never called for these champions. Instrumented
call counts over a full 133-candidate rank:

```
Aatrox    axis=ad  ranked=133  _ability_damage_calls=0
Ambessa   axis=ad  ranked=133  _ability_damage_calls=0
Veigar    axis=ap  ranked=134  _ability_damage_calls=135
```

RM-39 was framed as "credit ability haste in the hybrid DPS term". The hybrid DPS
term for an AD-axis champion contains no abilities at all. Ability haste is a
second-order missing term inside an entirely missing first-order term.

---

## 1. The blocking question

> **Should ability haste modulate a measured cast rate at all?**

**NO - and the question is a trap, because the measured rate should not be in a
DPS term in the first place.** Haste should modulate a theoretical in-combat rate,
which is the quantity that ought to be there instead. Four independent lines of
evidence, each verified this session:

### 1.1 Provenance: it is a whole-game average, not a combat rate

`scripts/build_spell_cast_rates.py:128-131` divides cast counts by
`m.game_duration_s`:

```python
"Q": (q_casts or 0) / dur,
"W": (w_casts or 0) / dur,
"E": (e_casts or 0) / dur,
"R": (r_casts or 0) / dur,
```

`dur` is whole-game duration, filtered only by `m.game_duration_s > 60`
(`build_spell_cast_rates.py:112`). The denominator therefore includes walking,
recalling, shopping, laning downtime, and time spent dead. Querying
`rewind_history.db` directly, **the median dead-time fraction of that denominator
is 10.9 percent for Aatrox (n=36 SR rows) and 10.8 percent for Ambessa (n=48)** -
over a tenth of the divisor is time the champion was a corpse.

The resulting numbers are not combat rates by any reading. Aatrox SR Q measures
0.10108 casts/sec, i.e. one Q every 9.9 seconds. His Q at this build has a 4.14s
effective cooldown and is a three-cast chain. Nobody has ever played Aatrox at one
Q per ten seconds in a fight.

This alone disqualifies the quantity from a combat DPS term, independent of haste.

### 1.2 Double-count: yes, the measured rate already embeds population haste

The medians are taken over games in which those players carried whatever items
they built. Aatrox and Ambessa players routinely build Black Cleaver (20 AH),
Death's Dance (15 AH), and Shojin (25 AH). The observed rate is therefore a
haste-inclusive observation. Multiplying it by a haste factor derived from the
candidate build double-counts the population's baseline haste.

This is in principle correctable - `participants` carries `item0`..`item6`, so the
population's average AH per champion is computable - but no such correction exists
today, and building one is strictly more work than the assigned shape.

### 1.3 Counterfactual: fatal, and structurally so

A build ranker asks "what happens if I buy THIS item". The lookup signature is
`ult_rates.py:201-206`:

```python
def get_spell_casts_per_sec(
    champion_name: str,
    key: str,
    mode: str,
    apply_canonical_cast_rate_keys: bool | None = None,
) -> float:
```

**It does not take `item_ids`.** The measured rate is not merely a poor estimator
of the counterfactual - it is mathematically constant across every candidate item
in the ranking. A term that is identical for all 133 candidates contributes exactly
nothing to their relative order. This is fatal, and it is the reason the measured
rate has to go rather than be re-weighted.

### 1.4 dps.py has no ability model, confirmed

`dps.py:1023` resolves `ult_casts_per_sec = get_ult_casts_per_sec(...)` and passes
it into `CallContext`. Reading the surrounding block, this is a **proc trigger rate
for ability-triggered item effects** (the Malignance Hatefog comment names it
explicitly), not an ability damage model. `compute_dps().weighted_dps` is
auto-attack DPS plus item procs. The brief's framing is correct: there is no
ability model in `dps.py` to extend.

---

## 2. Three stacked blockers between "ability haste" and "Shojin's rank"

Discovered in this order, listed outermost first. Each was verified live.

| # | Blocker | Evidence | Fatal to Shape A? |
|---|---|---|---|
| 3 | `compute_ability_dps` never invoked for AD-axis champions | call count 0 vs 135 control | **YES** |
| 2 | Haste-shortened cooldown discarded when `measured > 0` | `cps_source="measured"` on all 4 spells, both champions | the assigned seam |
| 1 | Shojin registered with **0.0 ability haste** | `item_ability_haste("3161") -> 0.0` | data bug |

### Blocker 3 - the axis gate (outermost, fatal)

`hybrid.py:73-79`:

```python
def _damage_axis(snapshot: DataSnapshot, champion_id: str) -> str:
    """Return ``"ap"`` when the champion is magic-primary, else ``"ad"``."""
    rec = snapshot.champions.get(str(champion_id)) or {}
    info = rec.get("info") or {}
    attack = int(info.get("attack", 0) or 0)
    magic = int(info.get("magic", 0) or 0)
    return "ap" if magic > attack else "ad"
```

Aatrox is `{'attack': 8, 'magic': 3}`; Ambessa is `{'attack': 9, 'magic': 0}`.
Both resolve to `"ad"`. All three `_ability_damage` call sites are gated on the
`"ap"` branch - `hybrid.py:462` (compute_hybrid), `hybrid.py:944` (rank baseline),
`hybrid.py:1032` (rank scored). The AD branch binds
`base_damage = dps_result.weighted_dps` and the ability path is dead.

Note also that 4 of 173 champions have `info.attack` and `info.magic` both absent
or zero, and `0 > 0` is False, so they silently fall to `"ad"` as well.

### Blocker 2 - the assigned seam

`ability_dps.py:1252-1259`, read this session:

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

`cooldown` above **is** haste-shortened (`_effective_ability_cd(base_cooldown, total_ah)`
at `ability_dps.py:1185-1188`) and is stored on the result, but it is consumed only
inside the `measured <= 0` branch. Measured is non-zero for all four spells on both
champions, so the haste-adjusted cooldown is computed and thrown away. Confirmed:
Aatrox Q `base_cd=6.0 -> eff_cd=4.14` yet `cps_source="measured"`, `cps=0.10108`.

### Blocker 1 - Shojin has no ability haste in the registry

`_item_ability_haste._ITEM_ABILITY_HASTE` holds 220 entries keyed id -> flat float.
Spear of Shojin (3161) is **0.0**. Its own DDragon description reads:

> Dragonforce: Gain 25 Basic Ability Haste.

Peers in the same build are registered correctly - Black Cleaver 20.0, Death's
Dance 15.0, Sundered Sky 10.0, Eclipse 15.0, Ravenous Hydra 15.0. This is the
hand-pinned-registry drift already logged in memory `reference_item_ah_registry_drift`.
Root cause is visible in the data: DDragon `stats` for 3161 is
`{'FlatHPPoolMod': 450, 'FlatPhysicalDamageMod': 45}` - AH lives in description
prose, not in structured stats - and `items_meraki.json` has `abilityHaste: null`.
There is no automated source to regenerate from.

Caveat for whoever fixes it: 25 **Basic** Ability Haste does not apply to R. The
registry is a flat scalar per item, so pinning 25 would over-credit the ultimate.
Correct modelling needs a basic-vs-ultimate split, which is a schema lift.

---

## 3. What the shape would have been

For the record, since the judges are comparing shapes. Seam
`ability_dps.py:1252-1259`, flag `apply_haste_scaled_cast_rates: bool | None = None`,
DEFAULT-OFF, threaded from the route the same way `apply_canonical_cast_rate_keys`
already is:

```
theoretical = (1.0 / cooldown) * mana_uptime          # cooldown already haste-adj
effective   = (1 - w) * measured + w * theoretical    # w = 0.0 at default
cps_source  = "measured" if w == 0 else "blended_haste_scaled"
```

At `w = 0.0` the expression binds the same float object and the path is
byte-identical. That property holds. It is also the only thing about the shape
that survives.

---

## 4. What would actually change if built - measured, not asserted

I layered the fixes in a single harness and re-ranked at each step. Level 13,
mode SR, build [Sundered Sky, Black Cleaver, Death's Dance, Sterak's],
target armor 100 / MR 70 / 2400 HP / 1200 bonus HP.

```
                                   champ     top1     Shojin   BotRK
BASELINE (shipping engine)         Aatrox    3084     47       2
                                   Ambessa   3153     42       1

LAYER 1  Shojin AH 0.0 -> 25.0     Aatrox    3084     47       2      <- NO CHANGE
                                   Ambessa   3153     42       1      <- NO CHANGE

LAYER 2  axis gate opened          Aatrox    6653     23       58
         (ability-only scoring)    Ambessa   6653     27       62

LAYER 2b auto + ability summed     Aatrox    3084     41       2
         (the coherent version)    Ambessa   3153     41       1

LAYER 3  + SHAPE A on top          Aatrox    3084     13       6
         (haste-scaled theoretical) Ambessa  3153     22       1
```

Read this carefully, because it cuts both ways.

- **Layer 1 alone is worth nothing.** Fixing the Shojin data bug moves nothing,
  because the term that would consume it is not called.
- **Layer 2 alone over-corrects.** Ability-only scoring makes Riftmaker (6653)
  the top item for Aatrox, which is wrong.
- **Layer 2b, the honest version, is disappointing.** Summing auto and ability
  moves Shojin only 47 -> 41 and 42 -> 41. The auto-attack term dominates so
  heavily that adding a correct ability term barely registers.
- **Layer 3 is the largest single mover.** Replacing the measured whole-game rate
  with the haste-scaled theoretical rate moves Shojin 41 -> 13 for Aatrox, a
  28-position jump, and finally displaces BotRK from rank 2 to 6.

So: Shape A's *mechanism* is vindicated and is the biggest lever in the stack.
Shape A's *scope* is refuted, because that lever is bolted to a gate that is shut.
Shape A shipped alone is a provable no-op.

**Reproduction caveat, stated honestly.** The exact ranks are sensitive to target
assumptions. Probing `/rank-bruiser` over HTTP without target stats (armor 0, MR 0)
put BotRK at 57 and Trinity Force at 1 for Aatrox. The brief's "BotRK #1 at every
target/level" did not reproduce for Aatrox at my settings - I measured BotRK #2
for Aatrox and #1 for Ambessa. The kill-test in section 0 is immune to this,
because it compares before and after inside one identical harness.

---

## 5. Cost estimate

Shape A as assigned, alone:

- Implementation: 2 to 3 hours. One seam, one flag, one thread-through.
- Verification: Tier-2. Full dual suite, DS :8893 restart, Share mirror, engine bump.
- **Ranking value delivered for RM-39 and RM-43: exactly zero.** Proven, not estimated.

The full stack that would actually close RM-39 and RM-43:

| Stage | Work | Cost | Risk |
|---|---|---|---|
| Shojin AH pin | 1 line, plus a basic-vs-ult schema decision | 1-2 h | low if flat, medium if split |
| Axis gate | AD-axis hybrid scores auto + ability | 1-2 sessions | **HIGH** |
| Shape A | blend, or drop measured entirely | 3-4 h | medium |

The axis-gate stage is the expensive one and carries the real risk: it changes the
score for **every** AD-axis champion routed to `ds.hybrid`, not just these two.
That is a broad regression surface and needs a full golden-diff review across the
bruiser cohort, not a two-champion spot check. Anyone scoping RM-39 as a one-seam
job is scoping the wrong thing. Realistic total: 3 to 4 sessions.

---

## 6. Strongest argument against my own shape

Beyond "it is inert as scoped", which is already dispositive, there is a second
problem that would bite even after the gate opens.

**A single blend weight cannot be correct, because the measured-to-theoretical
ratio is not constant - not across champions, and not even across spells within
one champion.** Measured this session:

```
Aatrox    Q  41.8%   W  17.6%   E  39.0%   R  34.3%
Ambessa   Q  56.5%   W  26.0%   E  34.1%   R  39.3%
```

That is a 3.2x spread inside Aatrox alone. A per-champion `w` is provably too
coarse. A per-spell `w` means 4 free parameters x 173 champions = 692 knobs, fit
against data that section 1 already established is the wrong quantity. Fitting
692 parameters to a biased estimator is not a model, it is a curve-fit that
launders the bias into the engine and makes it much harder to remove later.

**And the steelman I have to concede.** That spread is not pure noise. Aatrox W at
17.6 percent is Infernal Chains, a utility spell players genuinely cast less often
than it is available. The measured rate encodes real behavioural information -
"how often do players actually choose to cast this" - which a pure cooldown-inverse
model discards entirely. Layer 3 above buys its 28-position Shojin gain partly by
throwing that signal away, and it will over-credit low-utility spells as a result.

The correct destination is therefore neither of the two things on the table. It is
an **in-combat rotation model**: a per-spell cast rate derived from a fight-length
window, with haste shortening cooldowns inside that window, and the measured rate
demoted from a DPS multiplier to a *cast-propensity prior* on whether a spell is
used at all. That is a substantially larger project than any of the four shapes
being argued this session, and the honest thing to do is say so rather than ship
a blend weight that papers over it.

---

## 7. Recommendation

1. **Do not ship Shape A alone.** It is a measured no-op for RM-39 and RM-43.
2. **Re-scope RM-39 and RM-43.** The headline finding is not a haste gap. It is
   that AD-axis hybrid champions have no ability damage in their score at all.
   That finding is model-independent and should be filed against the axis gate at
   `hybrid.py:73-79` / `462` / `944` / `1032`, not against the cast-rate seam.
3. **Fix the Shojin AH registry entry regardless.** It is wrong today, it is cheap,
   and it will be needed by every downstream fix. Decide basic-vs-ultimate first.
4. **Sequence the real work** as Shojin AH -> axis gate (with cohort-wide golden
   diff) -> cast-rate model. Shape A's mechanism belongs in stage 3, where it is
   worth 28 ranks, and nowhere earlier, where it is worth nothing.

---

## Appendix - verification log

Every claim above was produced this session against engine 1.221.0 / patch 16.14.1
with DS live on :8893 (`/health` confirmed before probing).

Files read and line-verified (re-grepped after drafting, to defeat line rot):

- `agents/daemon_slayer/ability_dps.py:1252-1259` - the seam
- `agents/daemon_slayer/ability_dps.py:1185-1188` - haste-adjusted cooldown
- `agents/daemon_slayer/hybrid.py:73-79` - `_damage_axis`
- `agents/daemon_slayer/hybrid.py:462`, `:944`, `:1032` - the three `axis == "ap"` gates
- `agents/daemon_slayer/ult_rates.py:201-206` - lookup signature, no `item_ids`
- `agents/daemon_slayer/dps.py:1023` - `ult_casts_per_sec`, proc trigger not damage model
- `scripts/build_spell_cast_rates.py:112`, `:128-131` - whole-game denominator

Probe scripts (scratchpad, read-only, no production code touched):
`probe_axis.py` (call counts), `probe2.py` (AH registry), `probe3.py` (registry
contents), `probe4.py` (1e6 kill-test), `probe5.py` (layered counterfactual).

Route note: there is no `/rank-hybrid` route. `ds.hybrid` is served by
`/rank-bruiser` (`server.py:2094`), which is `rank_items_by_hybrid` in `hybrid.py:737`.
