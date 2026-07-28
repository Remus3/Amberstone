# DS ability-shaping notes - sourced, 2026-07-18

Deliverable of the DS_SWEEP phase-2 ability-shaping review (batch32, the roster-closing
session). Three DISTINCT populations of champions whose kit attributes are missing,
drifted, or unrepresentable. They share a symptom and nothing else - do not conflate them.

The single most useful result across all three: **most of these do not reach a live
output.** Counts below are measured, not inherited. Scope any fix to the reachable set.

  RM-95 alias/absent  5 flagged ->  2 genuinely absent, 0 of 3 alias misses change ranks
  RM-81 staleness    75 flagged ->  6 change any ranked order, 2 touch top-5, 0 change a core build
  empty damage_blocks 350 forms ->  3 champions reach a live output (Gwen, Kayle, Kog Maw)

---



---

## RM-95 - ability-data coverage (alias misses + genuinely absent)

# RM-95 - ability-data coverage: sourced per-champion note

Measured 2026-07-18 against live DS `:8893` (ENGINE 1.219.0, patch 16.14.1,
173 champions / 706 items) and the on-disk `data/daemon_slayer/16.14.1/` snapshot.
Every number below was produced this session; nothing is carried from a prior report.

---

## 0. Headline

The reported framing - "3 alias misses + 2 absent champs; staleness checker certifies
missing data as clean; **diagnostic not scoring**" - is **half right**.

| Claim | Verdict |
|---|---|
| 171 of 173 in `champion_abilities.json` | CONFIRMED |
| 3 alias misses / 2 genuinely absent | CONFIRMED (exactly 3 post-normalization) |
| Alias miss does not change rankings | CONFIRMED, and stronger than claimed |
| Staleness checker certifies them clean | CONFIRMED - closed-loop root cause found |
| "Diagnostic not scoring" | **REFUTED for Locke.** It is scoring. |

The one thing the RM-95 writeup got wrong is the most important thing in it.
**Locke ships a 0-of-6 AP-item build while being a 92%-magic-damage champion.**
That is a live, user-visible wrong-damage-type build order in a shipped artifact,
not a diagnostic annotation.

---

## 1. The two populations (confirmed, must not be conflated)

Set difference, `champions.json` (173, DDragon 16.14.1) minus
`champion_abilities.json` (171, Meraki bulk):

```
in champions.json but NOT champion_abilities.json: ['Locke', 'Zaahen']
in champion_abilities.json but NOT champions.json: []
```

### (a) ALIAS MISSES - 3. Data exists, lookup key is wrong.

`_norm_champ_key` (`core/daemon_slayer_client.py:1051-1052`) is
`"".join(ch for ch in s.lower() if ch.isalnum())`. A raw-key scan finds 21
champions whose display name differs from the DDragon id, but normalization
collapses 18 of them. Measured:

```
Wukong          -> wukong       | MonkeyKing -> monkeyking | match=False
Nunu & Willump  -> nunuwillump  | Nunu       -> nunu       | match=False
Renata Glasc    -> renataglasc  | Renata     -> renata     | match=False
Lee Sin         -> leesin       | LeeSin     -> leesin     | match=True
Cho'Gath        -> chogath      | Chogath    -> chogath    | match=True
Kai'Sa          -> kaisa        | Kaisa      -> kaisa      | match=True
```

Exactly 3 survive normalization. The count is right for the right reason:
these are the only three where the display name is not a punctuation/spacing
variant of the id but a genuinely different word.

### (b) GENUINELY ABSENT - 2. Locke and Zaahen. 171 + 2 = 173.

---

## 2. Root cause of (b): upstream, not stale local snapshot

`champion_abilities.json` `source` field:
`https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json`
Extractor: `tools/daemon_slayer_abilities_extract.py:113-114` (`MERAKI_BULK_URL`),
content pin `_EXPECTED_MERAKI_CONTENT_PATCH = "25.15"` at line 128.

**I probed that live endpoint read-only this session:**

```
LIVE Meraki bulk entries: 171
  MonkeyKing present= True     Locke  present= False
  Nunu       present= True     Zaahen present= False
  Renata     present= True
  Naafiri/Aurora/Mel/Yunara present= True
```

This is decisive and changes the fix: **a re-extract today would not help.**
Meraki upstream genuinely does not carry Locke or Zaahen - the `latest` endpoint
is frozen at content patch 25.15 and both champions post-date it. This is not a
local staleness problem, so the standing "never `--force` a Meraki re-extract"
rule is not even the relevant lever. The data must come from a different source.

`manifest.json` corroborates the shortfall independently:
`meraki_perlevel_backfill.champions_filled = 169` against
`ddragon_champion_count = 173`.

Both are new champions: DDragon keys 805 (Locke) and 904 (Zaahen), against a
roster whose next-highest keys are 950 Naafiri / 910 Hwei / 902 Milio.

---

## 3. Per-champion sourced notes

### 3.1 Wukong (DDragon id `MonkeyKing`) - ALIAS MISS

- **Kit:** present and current under `MonkeyKing`. Not on the RM-81 stale list.
- **Upstream:** nothing needed. Data is already on disk.
- **Fix:** cross-reference `champions.json` for the display name.
  `champion_abilities.json` entries carry **only** `P/Q/W/E/R` - no `name` field -
  so the index cannot be built from that file alone. The working pattern already
  exists 13 lines above: `champion_attackrange`
  (`core/daemon_slayer_client.py:1077-1080`) indexes **both** `cid` and
  `rec["name"]` from `champions.json`. `champion_has_ability_data`
  (`:1120-1121`) indexes `cid` only. That asymmetry is the whole bug.
- **Live impact: none.** See section 4.

### 3.2 Nunu & Willump (DDragon id `Nunu`) - ALIAS MISS + masks a real finding

- **Kit:** present under `Nunu`.
- **Second-order defect not in the RM-95 writeup:** Nunu is on the RM-81 stale
  list. Measured:
  ```
  Nunu & Willump  has_ability_data=False  ability_data_is_current=True
  Nunu            has_ability_data=True   ability_data_is_current=False
  ```
  The alias miss does not merely flip a presence flag - it **hides an
  already-detected staleness finding**. Called by display name, Nunu reports
  clean; called by id, it reports stale. Any caller on the display-name keyspace
  gets the wrong answer to a question the repo already answered correctly.
- **Fix:** same one-line-class fix as Wukong.

### 3.3 Renata Glasc (DDragon id `Renata`) - ALIAS MISS

- **Kit:** present under `Renata`, not on the stale list.
- **Route:** enchanter. The enchanter branch uses `_kitless_all_zero`
  (`core/daemon_slayer_client.py:1533`), a row-delta check that is
  name-independent, so this branch never consults the broken guard at all.
- **Live impact: none**, doubly so.

### 3.4 Locke, "the Ashen Exorcist" (key 805) - GENUINELY ABSENT - **SCORING DEFECT**

Kit sourced live from DDragon
`cdn/16.14.1/data/en_US/champion/Locke.json` and CommunityDragon
`v1/champions/805.json` (both carry full ability data):

- **P Silver Stake** - attacks deal bonus magic damage on-hit, scaled by target
  missing health.
- **Q Ritual Nails** - magic damage, marks with Soul Nails, slow. CD 10/9/8/7/6.
- **W Soul Ignition** - self-buff AS + MS; costs % current health as true damage
  per second, then heals a portion back.
- **E Ashen Pursuit** - teleport + dash, magic damage, consumes Soul Nails.
- **R Purgatory** - area magic damage + slow, **executes** marked champions below
  a threshold. CD 120/100/80.
- Tags Assassin/Mage, partype Mana, `damage_distribution` 92% magic / 4% physical.

**What actually ships today.** `archetype_for("Locke")` resolves to `mage`. The
mage branch computes rows, `_kitless_all_zero(rows, "delta_ability_dps")` is
all-zero (no kit data), so `fell_back = True` and control falls through to the
ds.dps carry path, which ranks on auto-attack DPS. Result, from the shipped
`build_orders_sr.json`:

```
Locke   magic_share=0.92  ap_items=0/6
  balanced: Blade of The Ruined King, Mercury's Treads, Heartsteel,
            Trinity Force, Lord Dominik's Regards, Terminus
```

Controls at comparable magic share:

```
Lux           magic_share=0.89  ap_items=5/6
Syndra        magic_share=0.88  ap_items=5/6
Renata Glasc  magic_share=0.61  ap_items=5/6
```

Locke is the only high-magic champion on the roster receiving a zero-AP build.
The fallback is behaving exactly as designed - with no ability data there is
nothing to price - but the **output** is a full AD bruiser line served to a
92%-magic assassin. This is scoring, and it is wrong, and it is shipped.

- **Upstream fix:** DDragon per-champion endpoint (already a manifest-cited RC
  source) or CommunityDragon. Both verified to carry the full kit today.
- **Engine notes for whoever wires it:** R is an execute (interacts with the
  existing lethality-execute / The Collector handling); P is on-hit magic scaled
  by missing health (the `ds.onhit` Slice B lane already models on-hit AP, and
  Locke's on-hit passive suggests the current `mage` route may itself be wrong);
  W is self-damage-then-heal (survivability axis, both signs).

### 3.5 Zaahen, "The Unsundered" (key 904) - GENUINELY ABSENT - kit-blind but plausible

Kit sourced the same way:

- **P Cultivation of War** - stacks of Determination from attacks/abilities on
  champions, bonus AD per stack; at full stacks bonus AD **and a revive**.
- **Q The Darkin Glaive** - double slash on next attack, bonus physical damage,
  heals **% of max health**; recast adds damage + knock-up. CD 10/9/8/7/6.
- **W Dreaded Return** - line physical damage, then **pulls** enemies in.
- **E Aureate Rush** - dash + slice, physical damage; edge hits add
  **% of target maximum health as magic damage**.
- **R Grim Deliverance** - passive **% armor penetration**; active grants damage
  reduction while casting, then a downward stab that heals for a portion dealt.
  CD 110/95/80.
- Tags Fighter/Assassin, `damage_distribution` 90% physical.

**What actually ships today.** `archetype_for("Zaahen")` resolves to `bruiser`.
Its build is AD, which is directionally correct, so this one does not look wrong
at a glance - but it is byte-identical to 8 other champions:

```
Zaahen balanced build shared by 9 champions:
  Gnar, Irelia, Jax, Nilah, Nocturne, Rek'Sai, Tryndamere, Yasuo, Zaahen
```

Zero kit differentiation. None of the four engine-relevant hooks in the kit are
priced: the % max-health heal (Q), the % max-HP magic damage (E), the % armor
penetration (R passive - which should shift Lord Dominik's valuation, and
Lord Dominik's is notably absent from the served build), or the revive (P).

**The revive is the sharpest gap.** CLAUDE.md records a shipped
"revive/second-life EHP-numerator multiplier" for Anivia and Zac. Zaahen is a
third instance of that exact modelled shape and is not receiving it.

- **Zaahen is also the one champion the bruiser guard exists for.** The comment
  at `core/daemon_slayer_client.py:1189-1190` says so explicitly: "This matters
  most for Zaahen, whose DEFAULT route IS bruiser."

---

## 4. Does the alias miss change rankings? CONFIRMED - and it is inert live

Live probe, `POST :8893/rank`, `top=200`, `enemy_ad_share=0.5`,
`enemy_ap_share=0.5`, rows under `ranked`:

```
display=Wukong          champion_id='MonkeyKing' champion_name='Wukong'
ddragon=MonkeyKing      champion_id='MonkeyKing' champion_name='Wukong'
  >> order=True  full_rows=True  WHOLE-RESPONSE-byte-identical=True
  >> differing top-level keys: []
```

Identical result for `Nunu & Willump` / `Nunu` and `Renata Glasc` / `Renata`.
All three pairs are **byte-identical across the entire response body**, including
the `champion_id` / `champion_name` echo. The DS server resolves aliases
correctly on its own.

Two corrections to the standing recipe fall out of this:

1. **There is no server-side `fell_back` key.** The `/rank` response top-level
   keys are `baseline_dps, budget, candidates_considered, candidates_evaluated,
   champion_id, champion_name, current_item_ids, level, mode, notes, phase,
   ranked, slot_count, sort_by, target_armor, target_bonus_hp, target_max_hp,
   target_mr`. `fell_back` is added RC-side at
   `core/daemon_slayer_client.py:1423`. The "only the fell_back flag differs"
   phrasing implies a server field that does not exist.
2. **Row keys are `item_id` / `item_name` / `delta_dps` / `effective_score` /
   `kit_axis_score`** - not `id` / `name` / `score`. Also `sort_by` reports
   `"delta"` while the row key is `delta_dps`; reading `row[sort_by]` yields
   `None` for every row. A probe that trusts `sort_by` as a key name silently
   reports all-null scores.
   **Trap:** on the bare `/rank` shape `effective_score` and `kit_axis_score` are
   `0.0` for **every** champion including Garen and Darius controls. Do not read
   that as kit-less evidence - it is the un-routed default. Kit degradation is
   only visible through the archetype-routed RC path.

**Why the alias miss is inert on the live path.** `champion_has_ability_data` is
consulted at exactly one site in the dispatcher - `:1423`, the **bruiser** branch.
Every other branch uses the row-based `_kitless_all_zero`, which is
name-independent. And the live consumer canonicalizes first:
`dashboard/routes_state.py:575` and `:951` both run
`champion = canonical_champion_id(champion) or champion` before dispatching, via
`core/archetype_picks.py:400`, whose docstring names "Nunu & Willump" and
"Wukong" explicitly. Measured:

```
champion          -> canonical   | has_data(raw) | has_data(canon) | archetype
Wukong            -> MonkeyKing  | False         | True            | bruiser
Nunu & Willump    -> Nunu        | False         | True            | tank
Renata Glasc      -> Renata      | False         | True            | enchanter
Locke             -> Locke       | False         | False           | mage
Zaahen            -> Zaahen      | False         | False           | bruiser

still FALSE after canonical_champion_id(): ['Locke', 'Zaahen']
```

So on the live path the alias miss is neutralized before the guard is reached.
Of the three, only Wukong even routes bruiser; Nunu is tank and Renata is
enchanter, so two of the three could never have tripped the guard regardless.

**The alias miss is real but latent.** It fires only for a caller that reaches
the bruiser branch without canonicalizing. That caller shape exists: the
`build_orders_*.json` keyspace is **display-name keyed** (173 entries containing
Wukong / Nunu & Willump / Renata Glasc and *not* MonkeyKing / Nunu / Renata),
while `champions.json` and `champion_abilities.json` are id-keyed. Feeding that
keyspace to the guard yields exactly the RM-95 five:

```
by build_orders_sr.json keyspace: FALSE (5) =
  ['Locke', 'Nunu & Willump', 'Renata Glasc', 'Wukong', 'Zaahen']
by DDragon id:                    FALSE (2) = ['Locke', 'Zaahen']
```

That is where the "5" in the RM-95 writeup comes from, and it is a genuine
latent trap - but it is not what is live today.

---

## 5. Staleness checker: CONFIRMED, with a closed-loop root cause

`tools/ds_wiki_staleness_check.py:365-367`:

```python
doc = _load_abilities(patch)        # reads champion_abilities.json
data = doc.get("data", {})
targets = sorted(c for c in data if champions is None or c in champions)
```

The target set is derived from `champion_abilities.json` itself. **The file that
is missing the champion is the same file that decides who gets checked.** A
champion absent there can never become a target, never gets fetched, never
appears in `stale_champions`. `_titles_for` compounds it: wiki page titles are
built from the *stored* ability names, so a champion with no stored data yields
no titles at all.

Then `champion_ability_data_is_current` (`core/daemon_slayer_client.py:1165-1170`)
returns `not index.get(...)` - absent from the report means `True`, "current".

Measured end to end:

```
_checked_champions = 171          (not 173)
Locke in stale list:  False
Zaahen in stale list: False
=> champion_ability_data_is_current('Locke')  = True
=> champion_ability_data_is_current('Zaahen') = True
```

**CONFIRMED: both missing-data champions are certified clean.**

Two fairness points. The function's docstring (`:1148-1153`) already documents
the fail-soft and states "True means 'no drift proven', not 'verified current'".
So the *behavior* is intentional; the defect is that the two signals are never
composed - nothing anywhere asks `has_ability_data AND is_current`. And the
checker's own source can cover them: I verified the wiki Data templates exist.

```
Template:Data Locke/Ritual Nails         missing=False rev=2026-07-14T19:37:23Z
Template:Data Locke/Soul Ignition        missing=False rev=2026-07-14T19:37:52Z
Template:Data Zaahen/The Darkin Glaive   missing=False rev=2026-05-05T12:34:13Z
Template:Data Zaahen/Dreaded Return      missing=False rev=2026-06-23T21:24:38Z
Template:Data Garen/Decisive Strike      missing=False rev=2026-04-02T16:52:46Z   (control)
wiki.gg control: HTTPError 401                                                    (as documented)
```

The only reason these two are unchecked is the roster the checker iterates.

---

## 6. A second defect found while tracing: the bruiser fallback label is incoherent

Not part of the RM-95 brief; surfaced by the same trace.

- **Mage / assassin / enchanter** kit-less path: `_kitless_all_zero` fires,
  `fell_back = True`, control falls through to the ds.dps carry path, which
  **re-ranks** and returns `scorer="dps"`, `archetype="carry"`
  (`core/daemon_slayer_client.py:1687-1707`). Coherent - the served build really
  is a carry build. This is Locke's path.
- **Bruiser** kit-less path: `:1401-1424` returns the hybrid rows **directly**,
  with `scorer="hybrid"` and no re-rank, only `fell_back=True`. But
  `dashboard/routes_state.py:701` then relabels the response
  `"archetype": "carry" if out.get("fell_back") else archetype`.

So a kit-less bruiser serves **ability-term-zeroed hybrid rows labeled "carry"**.
The comment at `routes_state.py:697` justifies the relabel with "the dispatcher
served a ds.dps carry build (fell_back)" - true for the other three branches,
false for bruiser. Zaahen is the champion that hits this.

---

## 7. Recommended action

**Split RM-95 into two items. They share a symptom and nothing else.**

1. **RM-95a, alias miss - trivial, do it now.** Index `champion_has_ability_data`
   by both id and display name, copying `champion_attackrange`
   (`core/daemon_slayer_client.py:1077-1080`) - join `champions.json` for the
   `name`, since `champion_abilities.json` has no `name` field. Add a regression
   test asserting all 173 `champions.json` display names resolve. Fixes the
   Nunu staleness-masking bug in the same edit. Zero ranking risk: proven
   byte-identical.

2. **RM-95b, absent champions - real work, and it is scoring.** Meraki cannot
   supply this, verified live today. Add a DDragon or CommunityDragon
   per-champion ability fallback for champions absent from the Meraki bulk map.
   Both sources verified to carry complete kits for Locke and Zaahen right now.

**Cheap interim mitigation for Locke, worth landing regardless.** The engine
already holds `damage_distribution` for all 173 (lolmath, per
`manifest.json.lolmath_counts`) - Locke's 92%-magic figure is on disk today.
Gate the kit-less ds.dps fallback on it: refuse to serve a zero-AP build to a
champion above roughly 70% magic share, or bias the fallback pool by damage type.
That converts a confidently wrong build into a defensible one without waiting on
upstream ability data.

**Also fix the checker's blind spot (one line).** Derive
`ds_wiki_staleness_check.run` targets from `champions.json` rather than
`champion_abilities.json`, and emit an explicit `missing_ability_data` bucket so
absence is reported as a finding instead of silence. Compose the two guards at
the call sites so `has_ability_data=False` can never read as clean.

**Correct the RM-95 memory note.** "Diagnostic not scoring" is wrong for Locke
and should not be carried forward - a future session reading that line would
deprioritize a shipped wrong-damage-type build order.

---

## 8. Probe artifacts

All under the session scratchpad, all re-runnable:

- `rm95_probe2.py` - alias byte-identity probe (corrected field names)
- `rm95_funcs.py` - real guards over the real rosters
- `rm95_reach.py` - canonicalization neutralization test
- `rm95_sources.py` - per-file roster coverage
- `rm95_kits.py` - DDragon + CDragon kit fetch
- `rm95_wiki.py` - wiki Data template existence
- `rm95_builds.py` - shipped-build damage-type comparison


---

## RM-81 - base-damage / cooldown staleness

# RM-81 staleness population - characterized

Measured 2026-07-18 on Legion. DS live: ENGINE 1.219.0, patch 16.14.1, 173 champions, 706 items.
All numbers below were produced this session, not carried forward.

## Bottom line

The reported 75 is REAL and reproducible - I re-ran the checker and got 75 stale champions /
123 findings, byte-matching the on-disk `ability_staleness.json` (generated 2026-07-18T11:59:22Z).

But 75 is the wrong number to act on. **6 of 75 change any ranked item order. 2 of 75 touch a
top-5 item. 0 of 75 change a recommended core build** - both top-5 cases are adjacent-pair swaps
between items that are already both in the core.

The gap is structural, not statistical: 43 of the 75 route to a scorer that never reads
champion ability data on that champion's axis, so their drift is unreachable by construction.

| Group | N | Why |
|---|---|---|
| UNREACHABLE - scorer never reads abilities | 25 | routes to `ds.dps` (15) or `ds.ehp` (10) |
| UNREACHABLE - scorer reads, but not this axis | 18 | 16 AD bruisers on `ds.hybrid`, 2 on `ds.hps` |
| REACHABLE - drift too small to move the order | 26 | ability-reading scorer, order identical |
| REACHES OUTPUT | 6 | order moves |
| ...of which a top-5 item moves | 2 | Mordekaiser, Naafiri - both adjacent swaps |

## The real count

```
patch=16.14.1  meraki_content_patch=25.15  checked=171  pages_fetched=754
stale_champions=75  findings=123   (base 81 / cooldown 42)
```

171 not 173: `champion_abilities.json` `data` holds 171 entries (2 champions absent - the
known RM-95 coverage gap).

## Magnitude - there is no rounding-noise bucket

The checker's tolerance is `_TOL = 1e-2`, which already eats representation noise. Result:

| Bucket | Findings | Champions (worst row) |
|---|---|---|
| trivial (<=2%) | **0** | **0** |
| small (2-10%) | 20 | 4 |
| moderate (10-30%) | 80 | 49 |
| large (>30%) | 23 | 22 |

So "trivial rounding vs real balance delta" is a false dichotomy for this population - every
surviving row is a real delta. The noise is filtered upstream. This means the count cannot be
reduced by tightening tolerance; it can only be reduced by the reachability argument below.

## Field breakdown

`cooldown` 42 - `base:<label>` 81, spread over 30 distinct labels. The top labels are
`Magic Damage` (29) and `Physical Damage` (20); the remaining 28 labels are 1-3 rows each
(`Guppy Damage`, `Damage per Snip`, `Magic Damage Per Bolt`, ...). No ratio rows at all -
by design, ratios are covered separately by `cdragon_ratio_drift.json` (1,046 rows, fields
`ap_pct` / `total_ad_pct` / `caster_max_hp_pct` / `bonus_ad_pct`, zero base / zero cooldown).

## Reachability - the number that matters

### Method

Scorer routing came from the real dispatcher (`core.archetype_picks.default_for_champion`),
not from assumption. Note its return is `(primary, secondary)`, NOT `(primary, source)` -
misreading that initially put Gwen and Kayle in the wrong bucket.

Which scorers read abilities at all, measured from module imports:

| Scorer | Archetype | Reads ability data | Evidence |
|---|---|---|---|
| `ds.dps` | carry | NO | `dps.py` imports only `data_loader` |
| `ds.ehp` | tank | NO | `ehp.py` imports `data_loader` + `survivability_credit` |
| `ds.ability` | mage | yes | `ability_dps.py` -> `abilities` |
| `ds.burst` | assassin | yes | `burst.py` -> `abilities` |
| `ds.hybrid` | bruiser | conditional | `hybrid.py` calls `compute_ability_dps` ONLY when `_damage_axis(...) == "ap"` (hybrid.py:462, 899) |
| `ds.onhit` | on-hit AP | yes | `onhit_dps.py` -> `ability_dps.compute_ability_dps` |
| `ds.hps` | enchanter | no effect | closed 10-item pool, champion-invariant |

`ds.dps` reading no ability data confirms `project_ds_vayne_silver_bolts_unmodelled` (CLOSED)
independently, from the import graph rather than a probe.

Then the experiment: load the stock `AbilitiesSnapshot`, build a second one with every drifted
`cooldown` / `damage_blocks[].base` replaced by the live wiki endpoints (linear ramp across the
same rank count - exactly what the wiki `{{ap|X to Y}}` macro means), run the champion's real
archetype rank function with each, and diff the ordered item list. Two configs: mid
(level 11, 100 armor, 70 MR) and late (level 18, 150 armor, 100 MR), `top_n=200`.

Injection points differ by scorer: `ds.ability` / `ds.burst` accept an `abilities_snapshot`
kwarg; `ds.hybrid` / `ds.onhit` / `ds.hps` do not and resolve through the module-level
`abilities._cache`, so that cache was swapped instead.

### Positive control - this is what makes the nulls trustworthy

A "no change" result is worthless if the harness is inert. Control: perturb one champion's
ability data by 10x base / 0.2x cooldown and require the order to move.

```
Ahri    ds.ability  SENSITIVE   first_div=1
Zed     ds.burst    SENSITIVE   first_div=2
Gwen    ds.onhit    SENSITIVE   first_div=1     <- proves the _cache swap works
Garen   ds.hybrid   *** INERT ***               <- real property, not harness failure
Lulu    ds.hps      *** INERT ***  pool=10      <- closed pool, champion-invariant
```

Because the same `_cache` mechanism is provably SENSITIVE on Gwen, the Garen and Lulu nulls are
a property of those scorers, not a broken harness. Garen is inert because he is an AD bruiser
and `_damage_axis` gates the ability read behind `== "ap"`. Lulu is inert because `ds.hps`
ranks a closed 10-item pool - which independently reproduces
`project_ds_hps_champion_invariant`.

Per-champion sensitivity control was then run for all 50 ability-route champions, giving the
18-champion "reads but not this axis" bucket (16 AD bruisers + Lulu + Nami).

### Result

Of 32 SENSITIVE champions, applying the true wiki values moves the order for **6**:

| Champion | Scorer | Field | stored -> wiki | true drift | first divergence | top-5? |
|---|---|---|---|---|---|---|
| Mordekaiser | ds.ability | Q base Magic Damage | [80, 230.6] -> [80, 220] | 4.6% | rank 2 | YES |
| Naafiri | ds.burst | R base Physical Damage | [150, 350] -> [150, 300] | 14.3% | rank 3 | YES |
| Heimerdinger | ds.ability | W base Initial Rocket | [40, 140] -> [50, 150] | 25.0% | rank 8 | no |
| Azir | ds.ability | W base Magic Damage | [50, 120.6] -> [50, 110] | 8.8% | rank 19 | no |
| Malzahar | ds.ability | W base Magic Damage | [17, 39] -> [12, 20] | 48.7% | rank 25 | no |
| Ahri | ds.ability | R base Magic Damage | [60, 120] -> [75, 175] | 45.8% | rank 37 | no |

Magnitude does NOT predict impact. Mordekaiser E drifts 16.7% and is inert; Mordekaiser Q
drifts 4.6% and moves rank 2. What decides it is whether the ranking is near-tied at that
point, not how big the delta is. Any "re-source the biggest deltas first" heuristic is wrong.

### Both top-5 cases are adjacent swaps, not build changes

```
Mordekaiser mid : Void Staff <-> Rabadon's Deathcap        (ranks 2/3 swap)
Mordekaiser late: Cryptbloom -> Mejai's Soulstealer        (rank 4)
Naafiri     mid : Serylda's Grudge <-> Bloodthirster       (ranks 3/4 swap)
Naafiri     late: no top-5 change (divergence at rank 57)
```

Every one is a reorder inside the already-recommended core. No champion acquires or loses a
core item. The Mordekaiser late row surfaces Mejai's Soulstealer, which is separately known to
be inflated by the RM-94 full-25-stack pin - that swap is partly RM-94 contamination, not RM-81.

## Defect found in the checker itself

5 of the 123 findings are false positives from a shape bug, and they are 3 of the 4 largest
reported magnitudes.

`ds_wiki_staleness_check.meraki_endpoints` compares `(seq[0], seq[-1])`. For some abilities the
stored `base` array is 18 elements - a 5-entry rank series CONCATENATED with a 13-entry
per-level series - so `seq[-1]` is a level-scaled number, not the max-rank base:

```
Mordekaiser Q base = [80, 117.6, 155.3, 192.9, 230.6,  13.2, 15.9, ... 45.0]
                      \___ the 5 real ranks ___/       \___ per-level tail ___/
```

Reported vs true magnitude on those rows:

| Champion | Ability | reported | TRUE |
|---|---|---|---|
| Mordekaiser | Q | 389% | 5% |
| Zoe | Q | 240% | 7% |
| Azir | W | 144% | 9% |
| Shyvana | E | 81% | 47% |
| Malzahar | W | 69% | 49% |

A decreasing base array (80 -> 45) is the tell: base damage never decreases with rank.
Recommended guard: in `meraki_endpoints`, take `seq[rank_count - 1]` where `rank_count` comes
from the ability's own `cooldown` length, and emit a `SHAPE_SUSPECT` marker when
`len(base) > rank_count`. Cheap, and it kills the three loudest false alarms.

This also invalidated my own first pass - lerping the whole 18-element array manufactured a
ranking change. The table above is from the shape-corrected re-run. The 6-champion set happened
to be stable across both, but for Mordekaiser and Azir the reason changed.

## Upstream source of truth and refresh path

The important finding: **the standard patch-refresh chain does NOT fix this.**

- Stored data comes from `tools/daemon_slayer_abilities_extract.py`, which pulls Meraki
  `https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json`.
- That `latest` endpoint is mutable but its CONTENT is frozen at patch 25.15, pinned as
  `_EXPECTED_MERAKI_CONTENT_PATCH` (extract:128) with a live guard at :796. Game patch is
  16.14.1. Re-running step 3 of the refresh chain reproduces the same stale numbers.
- CDragon cannot supply the fix as currently extracted: `cdragon_ratio_drift.json` is
  ratio-only (verified: 1,046 rows, `ap_pct` 660 / `total_ad_pct` 324 /
  `caster_max_hp_pct` 55 / `bonus_ad_pct` 7, zero base, zero cooldown), and
  `cdragon_spell_stats.json` carries only ammo / missile_speed / cc_tags / geometry.
- The wiki IS the working source. `wiki.gg` is 401; `wiki.leagueoflegends.com` works, and
  plain `index.php?...&action=raw` returns 301 - use the `action=query` API, which is what
  `tools/daemon_slayer_wiki_ability_extract.py` already does. I verified the wiki side
  independently through that fetcher:

```
Ahri/Spirit Rush             Magic Damage (75.0, 175.0)     stored (60, 120)
Heimerdinger/Micro-Rockets   Initial Rocket (50.0, 150.0)   stored (40, 140)
Mordekaiser/Obliterate       Magic Damage (80.0, 220.0)     stored rank-5 230.6
Naafiri/Hounds' Pursuit      Physical Damage (150.0, 300.0) stored (150, 350)
```

The wiki parsing is sound - the checker is right about the deltas, it is only wrong about
their size on the 5 concatenated rows.

`daemon_slayer_wiki_ability_extract.py` already exists and already fetches these exact
`Template:Data` pages, but writes a sidecar of cooldown flags / recharge / CC booleans /
geometry - not base damage. Extending it to emit base + cooldown per rank is the natural
refresh path and needs no new source, no new dependency, and no Meraki unpin.

## Prioritized action

**1. Do nothing about 69 of 75.** 43 are structurally unreachable; 26 are reachable but the
real drift does not move the order. Re-sourcing them buys zero output change. This is the
main result - the backlog item should be rescoped from "75 champions are stale" to
"2 champions show an adjacent-pair swap".

**2. Worth re-sourcing (6), in this order** - note the order is by measured rank depth, NOT by
drift size:

- **Mordekaiser** - Q, rank-2 swap, Void Staff vs Rabadon's. True drift only 4.6%; this is a
  near-tie, so treat the swap as low-confidence either way.
- **Naafiri** - R nerfed 350 -> 300 at rank 3. The cleanest genuine balance delta in the set.
- **Heimerdinger** - W 40/140 -> 50/150, moves rank 8.
- **Azir** - W, rank 19. Tail only.
- **Malzahar** - W, rank 25. Tail only.
- **Ahri** - R 60/120 -> 75/175, rank 37. Largest clean delta in the population and it lands
  at rank 37 of 144 - the clearest illustration that magnitude is not impact.

**3. Fix the checker's endpoint shape bug** (5 rows). Higher value per effort than any
individual champion re-source, because it stops the report from crying 389% at a 5% delta and
would otherwise keep mis-prioritizing every future sweep.

**4. Optional** - extend `daemon_slayer_wiki_ability_extract.py` to carry base + cooldown, which
converts RM-81 from a recurring manual audit into a data refresh. Only worth it if the ability
axis is going to carry more weight later; on today's evidence it changes 2 adjacent pairs.

**Do NOT** re-run `tools/daemon_slayer_abilities_extract.py` expecting a fix, and never
`--force` a Meraki re-extract - `latest` is mutable and the content is frozen at 25.15 anyway.

## Reproduction

```
python tools/ds_wiki_staleness_check.py --full            # 75 / 123, ~18 batched requests
```

Analysis scripts (scratchpad, `rm81work/`): `mag.py` (magnitude buckets) - `route.py` (scorer
routing) - `reach.py` / `reach2.py` (first-pass reach, superseded) - `control.py` (positive
control) - `sens.py` (per-champion sensitivity) - `shape.py` (concatenated-array
reclassification) - `reach3.py` (shape-corrected reach) - `attrib.py` (per-field attribution) -
`summary.py` (final grouping).

Gotcha: a stale `enum.py` / `__pycache__/enum.cpython-314.pyc` in the scratchpad root shadows
the stdlib and breaks `import json`. Run from a clean subdirectory.


---

## Empty damage_blocks / parse_status no_damage

# Empty damage_blocks / parse_status no_damage - enumeration and sourcing

Patch 16.14.1, ENGINE_VERSION 1.219.0, DS :8893 live. All counts below were
measured this session from `data/daemon_slayer/16.14.1/champion_abilities.json`
and from the engine's own loader, not carried forward from any prior report.

## 1. The real count

The brief asked for one number. There are three, and conflating them is the
main way this population gets misreported.

| Population | Count | Definition |
|---|---|---|
| Total ability forms | 927 | 171 champions, P/Q/W/E/R, multi-form expanded |
| `parse_status == "no_damage"` | **350** | the file's own status label |
| `damage_blocks` literally empty (`[]`) | **233** | zero blocks of any kind |
| zero `attribute_kind == "damage"` blocks, post-load | **358** | what the engine actually sees |

The three differ for reasons that matter:

- **350 vs 233.** 117 `no_damage` forms DO carry `damage_blocks` entries. Those
  blocks are non-damage attribute blocks with the field triple
  `(attribute, attribute_kind, raw_modifiers)` - for example Akali W
  `{"attribute": "Bonus Movement Speed", "attribute_kind": "duration", ...}`.
  `damage_blocks` is a misnomer: it is a general effect-block list. So
  "empty damage_blocks" and "no_damage" are NOT the same set, and a probe that
  reports one as the other is off by 117.
- **358 vs 350.** 8 forms are `parse_status == "ok"` yet contain zero
  damage-kind blocks: Aatrox R, Aphelios P, Janna E, Olaf R, Sona W,
  Tryndamere Q, Twitch R, Vayne R. All 8 are correct - they are heal / shield /
  duration / modifier blocks on abilities that genuinely deal no direct damage
  (Vayne R Final Hour, Twitch R Spray and Pray, Olaf R Ragnarok are pure buffs).

`parse_status` is identical before and after the engine's loader runs
(`{'ok': 571, 'partial': 3, 'unparsed': 3, 'no_damage': 350}` both ways), because
the override seam is default-OFF. See section 5.

### Distribution by slot

| Slot | no_damage | of total forms |
|---|---|---|
| P | 177 | 178 |
| W | 68 | 185 |
| E | 46 | 189 |
| R | 43 | 179 |
| Q | 16 | 193 |

**The single most important structural fact in this whole population: 177 of 178
passive forms are `no_damage`.** The only passive in the entire roster that is not
is Aphelios `The Hitman and the Seer`, and that one is `ok` with zero damage
blocks anyway (it is the weapon-swap bookkeeping passive). Every champion in the
roster (171 of 171) has at least one `no_damage` form, purely because every
champion has a passive.

This is not 171 individual extraction bugs. It is one systemic property: the
Meraki `leveling` -> `damage_blocks` pipeline structures ability damage from the
per-rank leveling table, and passives have no leveling table, so passive damage
is only ever present in prose.

## 2. Classification

Applied to the 350 `no_damage` forms.

| Class | Count | Share |
|---|---|---|
| (i) correctly empty | 193 | 55% |
| (ii) prose-only (damage or coupling asserted in text) | 157 | 45% |
| (iii) parse failure (structured data existed, was dropped) | **0** | 0% |

Of the 157 in (ii): 123 forms whose prose asserts real damage, 34 whose prose
asserts a stat coupling with no damage number. 54 of the 157 are already covered
by a hand-authored override registry entry; **103 are not**.

The (ii) figure is a keyword-detector upper bound (`magic damage` / `physical
damage` / `true damage` / `damage equal to` / `deals N` / `bonus damage`), so it
over-counts: it matches Kayn P ("each instance of damage dealt" - a stack
counter, not a damage source) and Kled P ("all damage dealt to the duo is
suffered by Skaarl" - a damage redirect). Hand-reading the first 40 put the
false-positive rate near 15%, so the honest range for real prose-only damage is
roughly **100-135 forms**, of which **65-90 are unseeded**.

### (iii) is empty, and that is a real finding

There are exactly 6 forms with `parse_status` `unparsed` or `partial`:
Illaoi E, Katarina R, MonkeyKing W, Nidalee Q1, Ryze R, Zeri E. **Every one of
them retained its damage blocks** (1 to 6 blocks each, all with damage-kind
blocks present). Illaoi E / MonkeyKing W / Ryze R carry the note
`no damage modifiers normalized` and still kept a block.

So there is no case in this dataset where structured damage existed upstream and
the extractor silently dropped it to empty. The extractor either structures the
block or the source never had one. Category (iii) should be closed, not
investigated.

## 3. Rammus - the named archetype, corrected

The brief's framing is right about the data and wrong about the remedy.

`data.Rammus.P` form 0, Spiked Shell: `parse_status: "no_damage"`,
`damage_blocks: []`, `damage_type: null`. The entire mechanic is one prose line:

> Innate: Rammus gains bonus attack damage equal to the sum of 15% total armor
> and 15% total magic resistance.

Confirmed post-load through the engine's own loader: `Rammus P Spiked Shell |
status no_damage | blocks 0 | DAMAGE-kind blocks 0`.

But Rammus is a poor archetype for the class, for two reasons.

**First, Rammus is already partly harvested.** Two of his three
prose-only mechanics have hand-authored registry entries:

- `_passive_reflect_overrides.py:89` seeds `("Rammus", "W", 0)` - the Defensive
  Ball Curl on-being-hit reflect.
- `_passive_resist_overrides.py:357` seeds Rammus W - both the flat and the
  percent-of-total-resist halves.

Only the P is unseeded. And Rammus W is itself a cleaner example of the class
than the P is: its `damage_blocks` capture the Bonus Armor and Bonus Magic
Resistance attributes, but the reflect damage - "enemies that use a basic attack
on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10% total magic
resistance) magic damage" - appears only in prose. A form can be partially
structured and prose-only at the same time.

**Second, Rammus W is a documented decision, not an oversight.** `CHANGELOG.md`
line 2549 records the 172-champion sweep that built the AA-routing allowlist:
"K'Sante P (bilinear caster-resist * target-HP, All Out gated) + Rammus W
(total-resist reflect) documented NOT-seeded." Someone looked at exactly this
case and chose to leave it.

## 4. What can reach a live scorer

This is the part that changes the shape of the answer.

### 4a. Prose can never reach a scorer, structurally

`effects_descriptions` is not a field the engine has. `AbilityForm` declares 16
fields at `agents/daemon_slayer/abilities.py:220-235` and `from_dict` at
`:244-263` parses exactly those. `effects_descriptions` is not among them - it is
dropped at load. Every one of the ~30 references to `effects_descriptions` inside
`agents/daemon_slayer/*.py` is in a comment or docstring citing provenance for a
hand-authored constant. None is a runtime read.

`kit_conversion.py:33-35` states the same conclusion independently, from the
other direction, and adds the measured block-key census: across all 1709 blocks /
171 champions the complete key set carries no attack-speed, crit, on-hit or DoT
key for any champion.

So the correct statement is not "no scorer fix can reach it." It is stronger:
**no amount of scorer work can reach prose, because the prose is not loaded.**
The only path from prose to an output is a hand-authored registry entry. That
path exists, is well-built, and is already carrying 142 seeded forms across 19
override registries.

### 4b. The seeded overrides are default-OFF

`_PASSIVE_DAMAGE_OVERRIDES` holds 32 entries. Measured post-load with the default
loader: **0 of 32 are live.** `_apply_passive_damage_overrides` runs only when
`AbilitiesSnapshot.load(apply_passive_damage=True)`, and `load_default()` does
not pass it (`abilities.py:297-305` docstring: "OPT-IN", "The default (flag OFF)
path never calls this").

Two of the 32 (Kayle E0, Kog'Maw W0) are additionally dead by a second gate: the
injector requires `parse_status == "no_damage"`, and at 16.14.1 both forms now
parse `ok`. That is registry drift - the Meraki pipeline caught up and the
override was never retired.

### 4c. Exactly 5 champions have a live path, and it is measured

A second allowlist, `_AA_ROUTED_ON_HIT_KEYS`, gates which registry entries route
onto the auto-attack cadence in `dps.py:1174-1212`. It holds 5 entries. I probed
the live DS server on `/dps` at level 11, SR, flag off vs on:

| Champion | Slot | Passive | flag OFF | flag ON | delta |
|---|---|---|---|---|---|
| Warwick | P | Eternal Hunger | 51.89 | 76.39 | +24.50 |
| Orianna | P | Clockwork Winding | 10.88 | 46.62 | +35.74 |
| Kayle | E | Starfire Spellblade | 51.59 | 76.75 | +25.16 |
| Gwen | P | A Thousand Cuts | 81.73 | 122.87 | +41.13 |
| Kog'Maw | W | Bio-Arcane Barrage | 94.52 | 184.66 | +90.14 |

Warwick / Orianna / Kayle measured at `items:[]`, `target_max_hp:0`. Gwen and
Kog'Maw are `target_max_hp_pct` scalings and read as zero-delta against a
zero-HP dummy - they were re-probed at `items:["3115"]`, `target_max_hp:2400`,
where both fire. Worth noting for anyone else probing this seam: a null result
here can be a probe artifact rather than an inert entry.

### 4d. The live default per route

- `/dps`: `apply_passive_damage` defaults **False**. Omitting it and sending
  `false` give byte-identical output (verified on all 5 champions).
- `/rank-onhit`: `rank_items_by_onhit` defaults the flag **True**
  (`onhit_dps.py:352`), and `core/daemon_slayer_client.py:1568` passes
  `apply_passive_damage=True` explicitly on the `onhit` archetype branch.
- The `onhit` route is taken only by champions in `core/ds_onhit_ap_roster.py`,
  which is exactly `{'Gwen': 1.0, 'Kayle': 0.3, 'KogMaw': 0.6}`
  (`archetype_picks.py:496-497`).

**So the live-reaching population is 3 champions: Gwen, Kayle, Kog'Maw.** Warwick
and Orianna have working, measured entries that no default route turns on -
their prose-only passive is worth +24.5 and +35.7 DPS respectively and is being
scored at zero in production.

Everything else in the 350 - including Rammus P, Rammus W, and all 103 unseeded
prose-only forms - has no live path at any flag setting. Not because a scorer is
wrong, but because no registry entry exists and no route would read it.

## 5. Per-champion detail

### 5a. Seeded and live-capable (5)

Measured deltas in the table above. Registry entries in
`agents/daemon_slayer/_passive_damage_overrides.py`; routing allowlist
`_AA_ROUTED_ON_HIT_KEYS` in the same file.

### 5b. Seeded but inert - the other 27 of 32

These have authored formulas that no route reads, because they are not on the
AA-routing allowlist (mark-consume / internal-cooldown / empowered-first-hit
cadences whose amortization was never settled - `CHANGELOG.md:3466-3473`):

`Aatrox P0`, `Akali P0`, `Aurora P0`, `Brand P0`, `Caitlyn P0`, `Darius P0`, `Ekko P0/W0`, `Galio P0`, `Gangplank P0`, `JarvanIV P0`, `Jhin P0`, `KSante P0`, `Kaisa P0`, `Khazix P0`, `Lillia P0`, `Lux P0`, `Qiyana P0`, `Renata P0`, `Sejuani P0`, `Sona P0`, `Taric P0`, `Twitch P0`, `Velkoz P0`, `Vex P0`, `Zed P0`, `Ziggs P0`

(27 forms across 26 champions.)

### 5c. Unseeded prose-only, real damage asserted

The actionable population. Grouped by champion; slot notation `P0` = key P,
form_index 0. Each was matched on a damage keyword in `effects_descriptions`
with no registry entry in any of the 19 override files.

`Akshan P0`, `Ambessa P0`, `Amumu P0`, `Aphelios P1/P4/P5/Q1/Q2/Q3/Q4/Q5/R0`, `Ashe P0`, `AurelionSol P0`, `Azir P0`, `Bard P0`, `Blitzcrank E0`, `Braum P0`, `Briar P0`, `Corki P0`, `Diana P0`, `Elise P0`, `Graves P0`, `Hecarim P0`, `Hwei P0`, `Irelia P0`, `Janna P0`, `Jinx Q0`, `Katarina P0`, `Kayle P0`, `Kayn P0`, `Kled P0/P1`, `KogMaw P0`, `Leona P0`, `Lissandra P0`, `Lucian P0`, `Lulu P0`, `MasterYi P0`, `Mel P0`, `Milio P0`, `MissFortune P0`, `Mordekaiser P0`, `Nautilus P0`, `Nocturne P0`, `Nunu P0`, `Ornn P0`, `Poppy P0`, `Pyke P0/R0`, `Quinn P0/R1`, `Rammus P0/E0`, `Rell P0`, `Rengar P0/R0`, `Riven P0`, `Rumble P0`, `Samira P0`, `Senna P0`, `Seraphine P0`, `Sett P0`, `Shaco P0`, `Sion P0`, `Skarner P0`, `Smolder P0`, `Sylas P0`, `TahmKench P0`, `Talon P0`, `Urgot P0`, `Volibear P0`, `Xayah P0/W0`, `Yone P0/E0`, `Yunara P0/W1`, `Zeri P0`, `Zoe P0`

(80 forms across 64 champions. Slot split: P 65, Q 6, W 2, E 3, R 4.)

#### Highest-confidence entries, prose quoted

Hand-verified by reading the source text. These are unambiguous flat on-hit or
on-cast damage with a clean formula - the same shape as the seeded Warwick /
Orianna entries, so they are authorable with no schema lift:

- **Corki P0 - Hextech Munitions** (`damage_type: None`)
  > Innate: Corki's basic attacks deal bonus true damage equal to 20% AD.

- **Ashe P0 - Frost Shot** (`damage_type: PHYSICAL`)
  > Innate: Ashe's basic attacks deal bonus physical damage equal to (75% + 40%) critical strike chance.

- **Lucian P0 - Lightslinger** (`damage_type: PHYSICAL`)
  > 25 seconds, which deals 50% / 55% / 60% (based on level) AD physical damage, increased to 100% AD against minions.

- **Akshan P0 - Dirty Fighting** (`damage_type: None`)
  > Innate: Whenever Akshan uses a basic attack, he fires an additional shot after a delay that deals 50% AD physical damage, increased to 100% AD against minions.

- **Leona P0 - Sunlight** (`damage_type: MAGIC`)
  > Allied champions' damaging attacks and abilities against a marked target will consume the mark to deal 32 : 151 (based on level) bonus magic damage.

- **Lulu P0 - Pix, Faerie Companion** (`damage_type: MAGIC`)
  > Each bolt deals 5 : 39 (based on level) (+ 5% AP) magic damage to the first enemy it collides with, for a total of 15 : 117 (based on level) (+ 15% AP) on hitting a single target with all three bolts.

- **Hecarim P0 - Warpath** (`damage_type: None`)
  > Innate: Hecarim gains bonus attack damage equal to 12% : 24% (based on level) of his bonus movement speed.

- **Janna P0 - Tailwind** (`damage_type: None`)
  > Janna's basic attacks on-hit and Zephyr deal bonus magic damage equal to 30% of her bonus movement speed.

- **KogMaw P0 - Icathian Surprise** (`damage_type: TRUE`)
  > Innate: Upon taking fatal damage, Kog'Maw enters a zombie state for 4 seconds, becoming ghosted and gaining 10% bonus movement speed that increases up to 50% over the duration.

- **Blitzcrank E0 - Power Fist** (`damage_type: PHYSICAL`)
  > Active: Blitzcrank empowers their next basic attack within 5 seconds to have an uncancellable windup, deal 100% AD (+ 25% AP) bonus physical damage and knock up the target for 1 second.

Corki, Ashe, Lucian and Akshan are every-auto-attack riders - the exact cadence
`_AA_ROUTED_ON_HIT_KEYS` was built for, and the exact shape whose per-hit
attribution the CHANGELOG calls "exact". They are the cheapest additions.

Hecarim P and Janna P are pure stat couplings with no damage number of their
own (bonus AD from bonus movement speed; bonus magic damage from bonus movement
speed). They are the true Rammus-P analogues and would need a coupling schema,
not a damage block.

### 5d. Unseeded prose-only, stat coupling with no damage number

`Akshan W0`, `Aphelios P2`, `Braum E0`, `Ezreal P0`, `Heimerdinger P0`, `Jinx P0`, `Karma E1`, `Kayn E0`, `Khazix R0`, `Leblanc P0`, `LeeSin P0`, `Nidalee P0`, `Renata R0`, `Renekton P0`, `Singed P0`, `Sion P1`, `Soraka P0`, `Sylas R0`, `TahmKench R0`, `Twitch Q0`, `Udyr P0`, `Varus P0`, `Vladimir P0`

(23 forms across 23 champions.) Rammus P0 sits in this group.
These cannot be expressed as a `DamageBlock` at all - they modify a stat, and
the block schema prices damage. See section 6.

## 6. Whether Rammus P is worth fixing

Stated plainly, because filing it as a bug would be wrong.

Spiked Shell converts armor and MR into bonus AD. To reach an output it would
need a scorer whose objective contains an AD term AND that Rammus routes to.
Rammus routes to the tank archetype and is scored by `ds.ehp`, whose objective
is effective HP. Armor items already rank at the top of that objective on their
resist value alone. Adding an armor-to-AD coupling would change Rammus's
modelled damage, which `ds.ehp` does not read, and would not move his item
order.

This is the same shape as `project_ds_vayne_silver_bolts_unmodelled` (closed:
`ds.dps` never reads abilities) and the RM-91 HP-as-damage finding. The coupling
is real, the extract genuinely lost it, and it still cannot change a live
recommendation. **File it as a documented modelling limitation, not a defect.**

The two findings here that ARE worth acting on are different:

1. **Warwick and Orianna are scored at zero for a working, measured entry.**
   +24.5 and +35.7 DPS at level 11. The formula is authored, the code path
   executes, the value is correct - no route turns it on. This is a one-line
   caller default, the same shape as the live-flip seams in
   `project_ds_live_flip_seams_unwired`.
2. **Kayle E0 is a probable double-count.** It now parses `ok` upstream, so the
   injector's `parse_status == "no_damage"` gate blocks the synthetic block -
   but the AA-routing path in `dps.py` reads the registry DIRECTLY
   (`dps.py:1183-1186` calls `aa_routed_on_hit_entry` then `to_damage_block`),
   bypassing that gate entirely. The two sources encode the same mechanic:

   - native Meraki block: `Passive Damage`, `base (15,20,25,30,35)`, `ap 20%`
   - override entry note: "35 (+ 10% bonus AD) (+ 20% AP) bonus magic on every
     basic attack (flat L13 max-rank of base [15,20,25,30,35])"

   Kayle is on the `onhit` route, where `compute_onhit_dps` sums
   `compute_dps` (auto half, now carrying the synthetic Starfire block) and
   `compute_ability_dps` (ability half, carrying the native one). Kayle also
   measured a live +25.16 DPS delta. This is the only item in this report that
   could be scoring something too HIGH rather than too low, and it is the one
   I would check first. Kog'Maw W0 is the same stale-registry shape but its
   native block should be confirmed separately before making the same claim.
