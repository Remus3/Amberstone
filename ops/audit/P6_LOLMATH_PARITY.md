# P6 LOLMATH BUILD-ENGINE PARITY - work-map

Operator-appended 2026-06-15 (Desktop handoff: `LOLMATH_VS_DS_SWEEP.md` + supporting
folder `lolmath_ds_sweep/`, both copied into `ops/audit/`). This is a P6 NEW-LIFT track
for the deep-audit loop: review the lolmath-vs-DS all-champion build sweep and implement
the real DS build-engine correctness gaps it surfaced. The Gemini director picks ONE
bounded slice per cycle, root-cause-first (see the `root-cause-fix` skill), validated
per-champion (not one generic shape - Engine/Build Conventions hard rule).

## DRAIN STATUS - RM-142, 2026-08-02 (read this FIRST; the slice bodies below are original 2026-06-15 text)

Every version number in the original text is STALE. Live at drain time: ENGINE
**1.269.0**, patch **16.15.1**, DS on **:8860** (the doc's `:8893` was retired,
RM-129). Re-derive from `data/daemon_slayer/current.txt` +
`agents/daemon_slayer/__init__.py` + `/health`, never from this doc.

| Slice | State |
|---|---|
| G1 wrong damage axis | **CLOSED 2026-08-02** - two waves, item 421 then RM-142. See the G1 section. |
| G2 low overlap | **CLOSED 2026-06-15** (item 425) - not a separate bug, routed. |
| G3 runes | **OPEN, but overtaken by events** - see below. |
| G4 boots pool | **SHIPPED 2026-06-15** (item 423, ENGINE 1.122.0 -> 1.123.0). |
| G5 item-pool gaps | **CLOSED 2026-06-15** (item 424) - premise falsified, there is no pool to fix. |
| G6 cost model | **CLOSED as by-design** - already filed as a BACKLOG row; do not re-file. |
| G7 comp harness | **BUILT + ANSWERED** - `g7_comp_harness.py` + `g7_comp_parity.json`. |

**G3 is not the row it was written as.** It says "DS models no runes"; that is no
longer true - `agents/daemon_slayer/` now carries 9 rune modules
(`_rune_offense_grants`, `_rune_resist_grants`, `_rune_self_heal`,
`_rune_shield_grants`, `_rune_flat_mitigation`, `_rune_health_grants`,
`_rune_hsp_amp`, `enemy_runes`, `rune_procs`) plus `core/rune_wpa.py`. What
remains true is narrower: `build_orders_*.json` has no rune PAGE (the per-entry
schema is `bias` / `comp_archetype` / `order` only). Re-scope before building.

**G7's answer was never written back into this doc.** `g7_comp_parity.json`
records that comp-matching does NOT recover parity: feeding lolmath's own comp
bucket (`burst_heavy`) scored mean overlap **1.488** against the blind `mixed`
baseline **1.837**, a delta of **-0.349**. `frontline_heavy` (2.0) tracks lolmath
best. So the G7 premise - that a like-for-like comp would close the gap - is
REFUTED by its own harness. Do not rebuild it.

**The "Gemini-consult" gate on G3 and G6 is DEAD** (Gemini retired 2026-08-01;
Claude self-adjudicates). Do not wait on a vendor that no longer exists.

## Inputs (in-repo, director-readable)

- `ops/audit/LOLMATH_VS_DS_SWEEP.md` - the full 172-champ table + appendix (the deliverable).
- `ops/audit/lolmath_ds_sweep/` - reproducer: `gen_md.py` (pairing script), `lolmath_sweep.json`
  (normal/gold-aware scrape), `ultimate_sweep.json` (cost-ignoring global-opt scrape), the
  playwright scrapers (`sweep.mjs`/`rescrape.mjs`/`ultimate.mjs`/`probe.mjs`), logs.
  `node_modules/` is gitignored - `npm install` to re-scrape.

## Provenance / what was compared

- lolmath patch 26.12 == DDragon 16.12.1 (same live patch). lolmath's constant default enemy
  comp = Jayce / Sejuani / Annie / Lucian / Thresh (4 squishy + 1 tank), headless, no live game.
- DS side = `data/daemon_slayer/build_orders/16.12.1/build_orders_sr.json` `mixed` variant
  (engine_version 1.120.0 in the sweep snapshot; live :8893 now 1.121.0 - re-derive before
  acting, do not trust the snapshot number per Verification Discipline).
- kit damage axis = `data/daemon_slayer/<patch>/champions.json` `lolmath.damage_distribution`
  (magical vs physical share) - the ground-truth tiebreak for G1.

## Slices (priority order)

### G1 - DS builds the WRONG damage axis - CLOSED 2026-08-02 in TWO waves (do NOT re-open on the 20-champ list below)

**WAVE 1, item 421 (2026-06-15, ENGINE 1.121.0 -> 1.122.0):** fixed the ARCHETYPE
RESOLVER (`core/archetype_picks.axis_correct_archetype`) against
`lolmath.damage_distribution`. Dropped the residual 20 -> 8, all 8 verified
by-design (see the G2 re-measure below).

**WAVE 2, RM-142 (2026-08-02, ENGINE 1.268.0 -> 1.269.0):** wave 1 was INCOMPLETE
and nothing caught it for 147 engine revisions, because the re-measure only
counted residuals and never asked whether the fix reached every CONSUMER. The
bruiser/onhit scorer keeps its own private axis, `agents/daemon_slayer/hybrid.py
_damage_axis`, which read the DDragon `info.attack`/`info.magic` cosmetic 0-10
designer ratings. The two resolvers contradicted each other on the same data for
12 of 173 champions. Only 3 reach `_damage_axis` (its only consumers are
`hybrid.py` = bruiser and `onhit_dps.py` = onhit): **Belveth** was broken
unmitigated (rated magic 7 / attack 4 against a 0.698-PHYSICAL kit -> took the
"ap" branch where `weighted_dps` is dropped outright -> shipped table built her
Liandry's #1 / Blackfire #2); **Gwen** and **KogMaw** were already rescued by the
local `_onhit_ap_axis` fallback. The other 9 (Alistar, Leona, Locke, Ornn,
Qiyana, Rell, Seraphine, TwistedFate, Vex) route to tank/mage/assassin/enchanter
and never call it.

**THE TRAP - re-read `hybrid.py:63-104` before touching this again.** The axis
split was LOAD-BEARING: it was the only thing keeping AP-SCALING TRUE rows out of
the RM-39/RM-43 AD-axis ability term (whose L2 widen credits PHYSICAL+TRUE).
Belveth R measures `ap_pct_sum` 300.0, Chogath R 150.0, and no damage-type filter
stops either. Correcting the axis ALONE would have traded one defect for another.
The guard is now EXPLICIT: `AbilitySpellDps.ap_pct_sum` + an AP-scaling filter in
`_physical_ability_damage`, with the RM-98 propensity delta riding the SAME
filtered list. Vayne Q (PHYSICAL but dual-scaling 75-115 pct AD AND 50 pct AP) is
deliberately EXCLUDED and pinned as a decision, mirroring how MIXED is HELD -
partial credit for dual-scaling rows is a SEPARATE design, not a filter widen.

**Measured result:** G1 residual 12 -> 11, `ok` 108 -> 109, zero collateral.
Belveth now builds BotRK / Trinity Force / Randuin's / Sterak's / LDR. Dual suite
28150 passed / 0 failed. **`onhit_dps._onhit_ap_axis` is now fully redundant**
(probed all 173 - zero remaining overrides) and was deliberately left in place;
removing it is a separate slice.

**The 11 remaining G1 residuals are ALL by-design or lolmath quirks - verified
per-champion, do NOT "fix" them.** 8 are tank-archetype and axis-neutral by
design (`_ARCHETYPE_AXIS["tank"]=None`): Amumu, Bard, Blitzcrank, Galio, Nunu,
Rakan, Singed, TahmKench. Udyr's kit is a genuine hybrid (0.565/0.380) that
clears neither decisiveness gate. Sett (0.006/0.736) and Zeri (0.224/0.731) build
correct AD and it is LOLMATH building the opposite axis. Note the probe flags G1
as `lm_ap>=2 and ds_ap==0` - measured against LOLMATH's build, NOT the kit - so a
residual row is not by itself evidence of a DS defect. Trinity Force is a probe
ARTIFACT (DDragon-tagged SpellDamage, 35 champions carry it correctly).

Related row filed this session: **BACKLOG RM-142-T** (tank + enchanter build
output carries zero champion differentiation - a coverage gap, NOT a defect).

ORIGINAL 2026-06-15 problem statement, kept for provenance:

### G1 (original) - DS builds the WRONG damage axis (20 champs)

DS_AD_vs_LM_AP (DS builds AD on an AP-scaling kit): Amumu, Blitzcrank, Diana, Elise, Galio,
Gragas, Gwen, KogMaw, Lillia, Lulu, Mordekaiser, Nidalee, Nunu, Rumble, Singed, TahmKench,
Teemo, XinZhao (+ AP-vs-AD inverses Pyke, Taric = DS_AP_vs_LM_AD).

LIVE-VERIFIED 2026-06-15 (mag / phys from champions.json): Gwen 0.703 / 0.126, Teemo 0.815 /
0.111, Rumble 0.905 / 0.040, Diana 0.817 / 0.102 = unambiguous AP kits, yet `build_orders_sr.json`
mixed builds crit/AD (BORK/IE/LDR/Berserker). Pyke 0.001 / 0.763 = unambiguous AD kit, DS builds
AP (enchanter Echoes/Ardent/Moonstone). These are real mis-assignments, not noise.

Root-cause candidates (grep + cite file:line before coding; do not scaffold against assumed API):
`core/build_order_precompute.py` (mixed-variant pool selection), `core/archetype_picks.py`
(damage-axis / archetype assignment), `core/archetype_mismatch.py` (already exists - check what
it covers), the DS scorers under `agents/daemon_slayer/`. The `mixed` build is the HZ-B1 precompute
output - the bug is upstream in archetype/damage-pool selection, so the fix must regenerate the
build_orders tables AND likely touch the scorer that feeds them.

Validation: per-champion (Engine/Build Conventions). For each of the 20, confirm the kit axis,
fix the assignment, regenerate, and re-rank "saner not different" - add a regression test per champ
asserting the dominant item axis matches the kit axis. Grep for sibling cases across modes
(aram/arena build_orders tables share the precompute) and the variants tables (HZ-B2). ENGINE bump
+ DS :8893 restart + Share re-sync (Tier-2). Do-not-flip-blind: this changes recommendations, so
gate on a re-rank sanity pass.

### G2 - low overlap - CLOSED 2026-06-15 (item 425; re-measured, NOT a separate bug; routed)

ORIGINAL: 59 champs, damage axis agrees but <=1 shared item vs the lolmath ULTIMATE. The
workmap predicted this is downstream of G3/G5/G6, re-measure after they land, chase only residual.

RE-MEASURE RESULT (durable probe `lolmath_ds_sweep/g2_remeasure_probe.py`, in-repo paths, run
post-G1/G4 at the live ENGINE 1.123.0 / patch 16.12.1; the snapshot was 1.120.0):

```
BEFORE (1.120.0): G1=20  G2=59
AFTER  (1.123.0): G1=8   G2=60  ok=101  nodata=3  (covered 169)
```

1. G1 dropped 20 -> 8. All 8 residuals are by-design, per-champion verified - ZERO accidental
   regressions from item 421's axis fix:
   - **Lulu** = operator pick `carry` (`data/cs_archetype_picks.json` source=user_cs, set 2026-05-17);
     the axis correction is applied ONLY to source=default and never touches an operator pick
     (`core/archetype_picks.py:121`). Crit-Lulu is an intentional off-axis operator build.
   - **Amumu, Blitzcrank, Galio, Singed, Tahm Kench** = tank archetype, axis-neutral
     (`_ARCHETYPE_AXIS["tank"]=None`, `archetype_picks.py:124`); a tank kit that deals magic still
     wants durability, never a glass-cannon pivot. BACKLOG role-reassignment, not an axis bug.
   - **Taric** (kit 0.61 AP, DS builds AP = matches kit) + **Xin Zhao** (kit 0.87 AD, DS builds AD =
     matches kit): DS is CORRECT; lolmath builds the opposite axis = lolmath quirk (item 421 finding).
   (Nunu dropped out of the residual because lolmath has no data for its "Nunu & Willump" slug ->
   counted in nodata, not G1.)
2. G2 held ~flat (59 -> 60). The axis fix correctly pulled the AP-damage champs (Diana, Gwen, Teemo,
   Rumble, Lillia, Mordekaiser, Kog'Maw, Gragas, Nidalee, Elise) OUT of G1 - they are now `ok` or
   sit in G2 with the RIGHT axis but different items. Fixing the axis does not make the SPECIFIC
   items match; that needs the design-level tracks. So the count is stable by construction, not noise.
   NOTE: G4 boots refresh does NOT move this metric - the overlap set subtracts BOOTS by design
   (`gen_md.py`), so G2 is purely a non-boots item-overlap measure.

G2 RESIDUAL = 3 root-cause buckets, every one downstream of an ALREADY-ROUTED track (per-champ
verified, builds dumped):
- **A. role-item vs lolmath-glass-cannon** (enchanters / supports / tanks: Janna, Sona, Alistar,
  Braum, Leona, Maokai, Milio, Nami, Nautilus, Ornn, Rell, Thresh, Yuumi, Zilean, Bard, Ivern,
  Seraphine, Morgana, ...): DS builds role-appropriate utility / heal / shield / durability (Janna ->
  Echoes of Helia / Ardent Censer / Staff of Flowing Water / Redemption / Moonstone), lolmath - a
  pure damage maximizer - builds raw AP ignoring utility (Janna -> Rabadon / Blackfire / Archangel's).
  overlap is the single durability/AP slot the optimizer keeps (Warmog's / Shadowflame). NOT a DS bug
  -> G6 / by-design (DS ships a role recommendation, not a damage-max).
- **B. AD scorer-valuation** (Aatrox, Fiora, Nasus, Darius, Jhin, Renekton, Riven, Senna, ...): axis
  agrees, lolmath loads lethality + kill-state passives (Hubris, Endless Hunger, Death's Dance, Spear
  of Shojin, Serylda's, The Collector), DS builds sustained-DPS / bruiser (BORK, Trinity, Sterak's,
  Heartsteel, Runaan's). overlap=1 = LDR, the one anti-tank slot both keep for the lone enemy tank.
  -> G5-residual (scorer valuation: passives needing kill-state, lethality-vs-sustained).
- **C. AP DoT-valuation** (Anivia, Swain, Lissandra, Aurelion Sol, Vladimir): axis agrees, lolmath
  loads AP damage-over-time burn (Liandry's Torment, Blackfire Torch, Hextech Gunblade), DS builds
  burst AP (Rabadon / Void Staff / Shadowflame / Stormsurge / Mejai's). overlap=1 = Shadowflame.
  -> G5-residual (AP DoT vs the single-rotation `ability` model).

CONCLUSION: G2 is NOT a separate fixable bug (workmap premise confirmed). The G1 axis fix landed
with zero regressions; the entire G2 residual is the G3 (runes) + G5-residual (scorer valuation) +
G6 (cost model / no-utility) class, already on the Gemini-consult queue. No new bounded slice. No
ENGINE bump, no build_orders regen, no DS restart, no Share re-sync (Tier-0 diagnosis).

### G3 - runes (DS models none; lolmath emits a full page per champ+comp)

Large, design-level. DS has no rune page in build_orders. Scope with Gemini before building -
this is a schema lift, not a slice. May overlap existing rune-WPA work (item 374 build_insights
rune tab). RESEARCH first; do not start blind.

### G4 - boots pool drift (mechanical, low-risk)

lolmath uses current 16.x upgraded boots (Spellslinger's Shoes, Gluttonous Greaves, Boots of
Swiftness, Sorcerer's Shoes); DS still uses legacy (Mercury's Treads x140, Berserker's Greaves x30).
Audit the DS boots pool vs live `item.json` upgraded-boots tags; refresh the pool. Mechanical,
good early win. Validate the upgraded-boot ids exist on map 11 / current patch.

### G5 - item pool gaps - CLOSED 2026-06-15 (item 424; NO pool gap; premise falsified)

ORIGINAL HYPOTHESIS: lolmath freely uses lethality (Hubris, Serylda's, Umbral, Collector),
AP on-hit (Nashor's, Riftmaker, Guinsoo's), current mythic-less items; DS's per-archetype
pool is missing entries. AUDIT RESULT: false - there is NO pool-membership gap.

Root-cause diagnosis (durable probes `lolmath_ds_sweep/g5_pool_probe.py` +
`g5_live_rank_probe.py`, re-run any cycle; verified live at ENGINE 1.123.0 / patch 16.12.1):

1. DS's candidate pool is `rank._filter_candidates` over ALL of items.json (706 items),
   gated only by: purchasable + gold.total>0, terminal (`into` empty), map-legal, budget,
   plus a 2-item non-coachable deny-set. There is NO per-archetype / per-stat pool whitelist.
   So every terminal purchasable map-legal item is already a candidate for every scorer.
2. Of 48 lolmath-favored items audited, REAL SR pool gaps = 0. All resolve to a canonical
   map11-legal id and pass the candidate gates. (v1 of the probe falsely flagged 42 as
   out-of-pool by indexing the 6-digit "22.."/"12.." Arena ALIAS ids, which are map11=False;
   see memory `reference_items_index_alias_ids`. The canonical short id is in-pool.)
3. Live-engine confirmation: every "missing" item appears IN the ranked list, just below the
   top-6 (Talon burst: Umbral #7 / Serylda's #10 / Youmuu's #12 / Hubris #13 / Profane #33;
   Lux ability: Blackfire #16 / Liandry's #23; Jhin dps: Collector #12 / Hubris #22).
4. DS recommends only ~60 distinct items across 172 champs x 4 comps; lolmath uses a far
   broader set. The breadth difference is SCORER VALUATION, not pool membership: the combat
   models undervalue (a) item PASSIVES that need kill/takedown state a static scorer lacks
   (Hubris snowball AD, The Collector execute, Death's Dance bleed/heal, Spear of Shojin
   ability-amp); (b) AP damage-OVER-TIME burn vs the single-rotation `ability` model
   (Liandry's Torment, Blackfire Torch); (c) the lethality-vs-sustained tradeoff inside the
   `burst` scorer (an assassin like Talon gets a sustained BORK/ER/IE build). Lethality
   itself IS modeled correctly (V14.1 1:1 flat pen, `effects.py:326`) - the gap is passive
   value + DoT + combat-philosophy, not ignored penetration.

CONCLUSION: do NOT add items to a pool (there is no pool to fix; a forced "fix" is churn +
regression risk). The residual is a scorer combat-model track in the SAME class as G3 (runes)
and G6 (cost model) - design-level, Gemini-consult before building, NOT a bounded slice.
Re-routed to the G3/G6 Gemini-consult queue. No ENGINE bump, no build_orders regen, no
DS restart this cycle (Tier-0 diagnosis).

### G6 - gold-efficiency / cost model (161/172 champs ultimate != normal)

DS has NO cost model: build_orders is a fixed list, neither gold-aware nor a cost-ignoring optimum.
lolmath's gold-efficiency actively shapes its normal build (appendix has the full per-champ diff).
DESIGN DECISION, not a bug - confirm with Gemini whether DS wants a cost model at all (RC's
build_orders is a recommendation list, not a purchase optimizer). May be CLOSED-as-by-design.

### G7 - comp-aware exact-match harness (research)

Feed DS the SAME 5-champ comp via `POST /api/ds-preview` (resolves live enemy stats) instead of
static `mixed`, for a like-for-like compare. This sweep used static DS builds. Research/validation
tooling, not a product change - lowest priority, build only if G1-G5 need a tighter oracle.

## Shared-frontier (neither tool models; out of scope unless operator asks)

lolmath's own "Not Yet Implemented": Dragon Soul buffs, Infernal Cinder, dynamic levels/items,
dynamic Grievous Wounds (DS models GW + ARAM/Arena tenacity already), dynamic tenacity, accurate
tower-damage. Logged for completeness; do not start.

## Don't-redo / guards

- Do NOT trust the snapshot's engine_version 1.120.0 - re-probe live :8893 (1.121.0+) each cycle.
- G6 cost model is likely by-design CLOSED - Gemini-consult before building.
- Per-champion validation is mandatory (a narrow first fix missed siblings before - items 208/213).
- Regenerating build_orders is Tier-2: ENGINE bump + DS restart + Share re-sync + dual suite.
