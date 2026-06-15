# P6 LOLMATH BUILD-ENGINE PARITY - work-map

Operator-appended 2026-06-15 (Desktop handoff: `LOLMATH_VS_DS_SWEEP.md` + supporting
folder `lolmath_ds_sweep/`, both copied into `ops/audit/`). This is a P6 NEW-LIFT track
for the deep-audit loop: review the lolmath-vs-DS all-champion build sweep and implement
the real DS build-engine correctness gaps it surfaced. The Gemini director picks ONE
bounded slice per cycle, root-cause-first (see the `root-cause-fix` skill), validated
per-champion (not one generic shape - Engine/Build Conventions hard rule).

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

### G1 - DS builds the WRONG damage axis (HIGHEST PRIORITY, correctness bug; 20 champs)

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

### G2 - low overlap (59 champs, axis agrees but <=1 shared item)

Not a separate bug - downstream of G3-G6. Re-measure after G1/G4/G5 land; only chase residual.

### G3 - runes (DS models none; lolmath emits a full page per champ+comp)

Large, design-level. DS has no rune page in build_orders. Scope with Gemini before building -
this is a schema lift, not a slice. May overlap existing rune-WPA work (item 374 build_insights
rune tab). RESEARCH first; do not start blind.

### G4 - boots pool drift (mechanical, low-risk)

lolmath uses current 16.x upgraded boots (Spellslinger's Shoes, Gluttonous Greaves, Boots of
Swiftness, Sorcerer's Shoes); DS still uses legacy (Mercury's Treads x140, Berserker's Greaves x30).
Audit the DS boots pool vs live `item.json` upgraded-boots tags; refresh the pool. Mechanical,
good early win. Validate the upgraded-boot ids exist on map 11 / current patch.

### G5 - item pool gaps

lolmath freely uses lethality (Hubris, Serylda's, Umbral, Collector), AP on-hit (Nashor's,
Riftmaker, Guinsoo's), current mythic-less items. Audit DS per-archetype pools for missing
entries vs live `item.json`. Per-archetype, per-mode. Pairs with G1 (right axis needs right pool).

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
