# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the batch26-31 sweep session relocated the batch20 block `2026-07-18g` to `docs/history_notes.md`; newest 3 = the batch26-31 sweep session `2026-07-18j` + batch21-25 `2026-07-18i` + the RM-86 L1 engine session `2026-07-18h`). NOTE: `scripts/wakeup_prune.py` is a silent NO-OP against these headers - its `SESSION_RE` requires a word boundary after the day, so a letter-suffixed header like `# 2026-07-18h` never matches and it reports "nothing to do" at any file size. Relocations are manual until that is fixed (filed as its own task).

---

# 2026-07-18j (DS_SWEEP batch26-31 -> 169/173: 30 champions in one session; 30 GAP, 0 REFUTE, THREE new shapes, and the archetype-invariance measurement that reframes the whole sweep)

Read-only research, NO engine change. LEDGER 944 + 945. Two commits:
`6f927b40` batch26/27/28 (Thresh..Viktor, 139 -> 154) and `525ac845`
batch29/30/31 (Vladimir..Zeri, 154 -> 169). CI is path-filtered for docs-only
pushes BY DESIGN (`paths-ignore: '**/*.md'`), so no run is expected on either;
the local ASCII-hygiene gate is the backstop and is green (13 passed), ruff
clean. **FOUR champions remain: Ziggs / Zilean / Zoe / Zyra.**

THREE NEW SHAPES. **RM-93** - support-quest item CANDIDACY is inconsistent
across archetype pools: Zaz'Zak's 3871 and Bloodsong 3877 are candidates on
ZERO routes despite carrying full modelled damage formulas and a guard suite,
while their three siblings rank on mage+tank but not enchanter. Canonical is
Xerath (Zaz'Zak's at **94.28% presence**, candidate nowhere, WR below his own
support average). Filter-list work, not L2. **RM-94** - snowball-conditional
stacks pinned at FULL value: `_effects_data.py:3257` pins Mejai's at
`bonus_ap_stacked=125.0` under a "sustained-peak convention" comment that
conflates "reachable in one fight" (Black Cleaver) with "requires already
having won" (25 kill stacks). Mejai's ranks **#6 for every mage** at 2-5% real
presence. NOT win-rate contamination - DS default is pure simulation, so it
reaches the same wrong item by a different route. **RM-95** - ability-data
COVERAGE, and it is a DIAGNOSTIC defect, not a scoring one: five champions have
no reachable ability data (3 alias misses where the data exists -
Wukong->`MonkeyKing`, Nunu & Willump->`Nunu`, Renata Glasc->`Renata` - plus
Locke and Zaahen genuinely absent), and `champion_ability_data_is_current()`
returns True for ALL FIVE because absent data cannot be drifted. The RM-81
staleness program therefore under-reports by exactly the set it should flag
hardest.

**THE HEADLINE IS NOT A SHAPE - it is a measurement.** The mage head is EXACTLY
invariant across seven mages spanning both batches: Liandry's #1, Blackfire #2
and Mejai's #6 for ALL SEVEN, Luden's Echo #13 for six. And BotRK is #1 on
**11 of 11** AD-routed champions. Only one of the seven mages (Viktor) has its
real first legendary at the top. This mechanically explains the standing
batch15 fact that "Luden's Echo appears ZERO times" as a first legendary across
173 champions - it ranks #13 invariantly, so it structurally cannot be first,
while being the real #1 for Xerath (87.10%), Vex (88.44%) and Vel'Koz (63.67%).
**Framing that matters: the BotRK lead is not uniformly WRONG, it is uniformly
UNCONDITIONAL** - correct for Warwick (76.95%) and Yone (91.8%), wrong for
Viego (Q duplicates it; real item dead at 4.12% / 46.15% WR), Zeri (right-click
applies NO on-hit at all) and Urgot (fixed 3.0 attack speed). A remedy must be
a DISCRIMINATOR, not a demotion. Also generalized: the zero-AD Zeal class is a
uniform #20-#43 (carry) / #38-#74 (bruiser) band across 11 champions vs IE at
#6-#16, so it is a stat-signature effect, not per-champion.

**DO NOT REDO / self-corrections that already landed.** (1) The RM-95 alias
miss does NOT degrade rankings - display-name vs DDragon-id ranking is
BYTE-IDENTICAL, only the `fell_back` flag differs (consistent with the closed
Vayne finding that the scorers never import `abilities`). (2) The batch17
"Nunu [GAP route]" verdict is NOT mis-attributed - that analysis used the id
form. Both claims were mine, both were wrong, both were caught by measurement
before reaching the tracker. (3) The Shieldbow/Hexoptics control does NOT show
the scorer blind - it separates them 10-11 places in the CORRECT direction, so
the defect is magnitude, not blindness. (4) "Xin Zhao MISSING from
champions.json" was a lookup error; the file is DDragon-keyed (`XinZhao`), all
173 present. (5) **Vayne was a roster HOLE**, backfilled from her closed
do-not-re-probe memory, not re-probed - second instance of that trap.
(6) Engine credit recorded so it is not re-flagged as a gap: the shipped
artifact correctly gives Yuumi NO boots, and BotRK #1 is right for Warwick/Yone.

**PROBE RECIPE IS DRIFTED - fix before reuse.** Result rows live under key
`ranked`, NOT `rows`/`results` (a faithful probe returns pool=0 for every
champion and looks like total engine failure); there is NO
`champion_has_ability_data` response key (use
`champion_ability_data_is_current()`); the tanky/squishy pair varies only
DPS-side inputs so an identical TANK order across both is CORRECT, not
target-blindness (probe tanks via `enemy_ad_share`/`enemy_ap_share`); and the
three item files have three non-guessable shapes (`items.json` is DDragon
`j['data']`, `items_meraki.json` has NO stats block, `build_orders_sr.json`
nests under `build_orders`). Shell hazard: a double-quoted bash string eats
backticks as command substitution - write memory/doc appends from a Python file.

NEXT: last 4 champions (Ziggs / Zilean / Zoe / Zyra) to close the roster at
173/173, then the ability-shaping review for champions missing kit attributes
(note them for upstream sourcing), then decide what to DO with the collected
champion/build data and land it for live usage.

# 2026-07-18i (DS_SWEEP batch21-25 -> 139/173: 25 champions in one session; 23 GAP + 2 REFUTE, TWO new numbers, ONE self-retraction)

Read-only research, NO engine change. LEDGER 942 + 943. Three commits:
`97673b94` batch21/22/23 (15 champs, 114 -> 129), `25553130` the probe-depth
correction, `f9466ea5` batch24/25 (10 champs, 129 -> 139). CI is path-filtered
for docs-only pushes by design, so no run is expected on any of the three; the
local ASCII-hygiene gate (13 passed) is the backstop and it is green.

NEW: **RM-91** - bonus HP scored as EHP-only, so HP-to-damage kits are
undervalued (Sejuani / Sett / Shen / Sion / Skarner / Tahm Kench). Randuin's is
engine #1 for all six and in the real core of none. **RM-92** - non-output item
value is unpriced, because every scorer optimizes self throughput (Soraka /
Sona / Swain / Sylas / Taric / Smolder). Canonical: **Soraka's 90.28%-presence
Moonstone Renewer ranks #10 of 10, dead last** - the mechanism is
complementarity, since an objective that scores items standalone must rank a
gap-filling item last. Tahm Kench vs Taric is the matched pair that separates
the two shapes. Both are L2 objective-coverage, NOT L1 lowering-gate work.

**DO NOT REDO / read before trusting older entries.** (1) The
cross-axis-pool-partition shape is **RETRACTED** - it came from reading the
recipe's `top=40` as the pool size. Real pools: carry 111, bruiser/tank 143,
mage 144, and all 118 purchasable terminal SR legendaries are candidates
somewhere. Probe at `top=200`. (2) Check `gold.purchasable` before filing any
absence as an omission - transform targets (Seraph's Embrace, Fimbulwinter) and
the guard-tested Dream Maker / Diadem of Songs are correct exclusions. (3)
`data/meta_build/sr_champion_builds.json` can name the WRONG build as primary
(it gave Shyvana's 5.06% path as her core) - cross-check only, never a
substitute for the research agent. (4) RM-90 is re-measured: GROUP A is 10 and
GROUP B is 28, and GROUP B is the generic tank template, not a support cohort.

NEXT: Thresh (strict alphabetical), next GAP spec = RM-93, 34 pending. The
cheapest actionable finding banked this session is NOT either new number - it is
the carry pool being a fixed 111 items that categorically exclude Black Cleaver /
Spear of Shojin / Bloodsong / Stridebreaker / Sterak's Gage. That is a
filter-list edit, not objective work.

---

# 2026-07-18h (RM-86 L1 SHIPPED + L2-for-hps REFUTED + enchanter registry closed; ENGINE 1.217.0 -> 1.219.0, 3 engine commits)

First ENGINE work of the RM-86 arc after four read-only research batches.
Commits: `17ab86ea` (L1 gate, 1.218.0), `09211c10` + `c6980918` (docs), `b7d7096f`
(enchanter registry, 1.219.0). LEDGER 940 + 941. CI green on 17ab86ea.

**L1 SHIPPED** - `agents/daemon_slayer/kit_conversion.py` + default-OFF
`kit_conversion_strength` on carry / assassin / mage / tank. Byte-identity proven
FULL-ROSTER: both build-order tables regenerated 173 champs x 3 modes returned a
2-line stamp-only diff. Reached: Naafiri BotRK leaves #1 both routes; Orianna
Liandry's leaves #1 at 0.50 while Blackfire is NOT suppressed; Poppy control held.

**TWO SPEC CORRECTIONS (spec section 10) - do NOT re-derive:**
1. The vector CANNOT come from `damage_blocks` - no attack-speed / crit / on-hit /
   DoT key exists in any of the 1709 blocks across 171 champions, and the loader
   drops `effects_descriptions` (`abilities.py:220-263`). It is a prose-seeded
   curated registry. Snapshot holds **171** champions, not 173.
2. A monotone-lowering sort-key gate can only push bad items DOWN, never push a
   good item UP past untouched neighbours. Olaf Stridebreaker (#34, tied to BotRK
   by identical `PercentAttackSpeedMod: 0.25`) and Pantheon Black Cleaver #29 /
   Heartsteel #3 are therefore L2 objective-coverage, NOT L1. Standing rule now in
   the tracker.

**L2-for-hps is REFUTED - do NOT build it.** Forcing `apply_ability_hsp_amp` ON
leaves all 8 enchanters byte-identical to each other (one adjacent swap, same for
everyone). REFUTE condition 2 satisfied -> finding (c) is RC-2 pool, not RC-1.
Spec section 3 was ALSO factually wrong twice: `hps.py:648` DOES import
`ability_hps`, and `hps.py:679` adds `ability_hps_total` unconditionally.

**Enchanter registry closed (1.219.0).** The handed list of "10 missing items" was
~80% wrong; re-derived by scanning the catalog. Only Dawncore 6621 (terminal, pool
9 -> 10, climbs #9 -> #5 with depth) and Whispering Circlet 2526 (non-terminal,
registered-but-unranked like Forbidden Idol 3114) belonged. 8 rejections each
pinned by a guard test. Does NOT fix the invariance - a test pins that.

**NEXT:** DS_SWEEP 15 champions (3 batches of 5). **Briar is an unnoticed hole** -
`- [ ] Briar` at tracker line 289 with no verdict and no FENCED note, silently
skipped in the B-batch. Roster markers are `[GAP RM-nn]` / `[REFUTE]` / `[ ]`, so
`grep -c "^- \[x\]"` returns 0 and looks catastrophic - do not panic.
Two future-proofing chips queued (Arena mirror leakage guard; patch-vintage drift
guard). Do NOT rewrite `enchanter_items.json` `_meta.patch` 16.9.1 -> 16.14.1.

---
