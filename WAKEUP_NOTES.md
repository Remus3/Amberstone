# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the Term A session relocated `2026-07-18i` batch21-25 + `2026-07-18h` RM-86-L1 to `docs/history_notes.md`; newest 3 = Term A `2026-07-18l` + roster-closed `2026-07-18k` + batch26-31 `2026-07-18j`). NOTE: `scripts/wakeup_prune.py` is a silent NO-OP against these headers - its `SESSION_RE` requires a word boundary after the day, so a letter-suffixed header like `# 2026-07-18h` never matches and it reports "nothing to do" at any file size. Relocations are manual until that is fixed (filed as its own task).

---

# 2026-07-18l (C1 audit resized Term A + Term A SHIPPED 1.220.0 + a self-inflicted false bug retracted; 2 commits)

**C1 first, and it changed the work.** Re-adjudicated all 21 RM-92 rows at BUILD
DEPTH (7 parallel agents, live 1.219.0, `/rank-<archetype>`, mode=SR, top=200,
depths 0-3, cross-checked vs all 3 shipped variants + `gold.purchasable`):
**21 -> 17 REAL / 2 ARTIFACT / 2 POOL-CANDIDACY.** Deflation is 19%, not the ~33%
the 6-row sample projected. **Composition was the finding, not the count** -
ABILITY-HASTE 5 / MOBILITY 4 / ALLY-FACING 3 / CC-UPTIME 2 / OTHER 3. Soraka's
"#10 of 10 dead last" canonical instance is a PROBE ARTIFACT (#3 at depth, and
the shipped order already buys it); Yuumi's "most complete instance" too. That
cut Term A's justification from an assumed 13 champions to **2 measured** ones,
so the operator swapped the "exactly 13 changed" golden-diff gate (churn) for a
correctness gate on Taric + Thresh. Re-derivation also found **14 raw `affects`
hits, not 13** - the old note dropped Nunu.

**Term A SHIPPED** `43a2e0ea` (ENGINE 1.220.0): `score_by="team_blended"` on
`ds.ehp`, DEFAULT-OFF. Taric Locket #24 -> #6, Thresh #20 -> #5, 12 gated
champions, verified live on `:8893`. Two NEW modules are both thin - the item
side is an ADAPTER over the existing curated `enchanter_items.json` (not a new
registry), the champion side is a BOOLEAN `affects` gate. ZERO new constants.
The gate is load-bearing: disabled, Locket enters the top-6 for Rammus too.

**I filed a false bug and retracted it** `7b116d50`. Claimed the Arena table
ships map-30-illegal items; it does not - all 9 tables audit clean, ARAM too. I
read item NAMES then resolved them to BASE ids; base and mirror share a name
(Moonstone = 6617 map30=False AND 226617 map30=True) and the table stores the
mirror. Shipped `tests/test_build_order_map_legality.py` so it cannot recur -
this also closes RM-04's "correct by luck not construction" gotcha.

**Do NOT redo:** the RM-92 population audit (done, LEDGER 950). Term A (shipped;
live default-ON flip is the only open tail). The Arena map-30 "bug" (does not
exist - run the guard test, 1 second). The 2 `coach_poll_offload` failures are a
load flake that passes standalone.

**Next:** the ABILITY-HASTE class is the largest measured RM-92 residual (5
champions) but only `ability_dps.py` prices AH - `dps`/`hybrid`/`ehp`/`burst`/
`hps` carry ZERO, and carry/bruiser have no cooldown model to compress, so it is
RM-86-sized. Size it before committing.

---

# 2026-07-18k (ROSTER CLOSED 173/173 + 3 bugs landed + repo-wide .md prune; 6 commits)

**DS_SWEEP is DONE. 173/173 - GAP 135, REFUTE 35, FENCED 3, Remaining 0.** Batch32
closed it: Ziggs [REFUTE], Zilean [GAP RM-96 NEW], Zoe [GAP RM-40], Zyra [GAP RM-97
NEW]. RM-96 = ds.hps prices heal/shield-CONDITIONAL passives at full value on a
champion who cannot trigger them (Zilean pool inverted at #4/#5). RM-97 = persistent
pet damage has no schema slot (Zyra plants 55-65 pct of her damage, scored zero;
generalizes to Heimerdinger / Ivern / Yorick). Both SPEC-ONLY. Next free spec = RM-98.
**Do NOT re-open the roster.**

THREE BUGS LANDED, and in all three the briefed fix was WRONG - check the measurement
before implementing anything handed down:
- **RM-93** as briefed was a REGRESSION. Admitting Zaz'Zak's/Bloodsong ranks Bloodsong
  #2 Vel'Koz / #3 Jinx. Real defect was the inverse: the SR deny held 2 of 5 Bounty of
  Worlds upgrades. Landed sibling-complete (+3 ids), SR pool 144 -> 141, no ENGINE bump
  (precedent 415c1795). Live-verified on restarted :8893.
- **RM-81** prescribed fix would have CRASHED the tool (Aurelion Sol Q IndexError kills
  the sweep) plus 12 bad truncations. Real tell is an INTERNAL DROP, not end-to-end
  decrease. Mordekaiser Q 388.9 pct -> 4.81 pct, SHAPE_SUSPECT marker added.
- **Unpaired enemy-share** silently returned NO recommendation (reproduced: Thresh 141
  rows -> None). 50.1 pct of real comps hit it. `_resolve_enemy_shares` derives the
  partner. Hard prerequisite for the archetype program.

DOCS: BACKLOG 285 -> 141 lines (15 teardowns relocated VERBATIM to
`docs/research/COMPETITOR_LIFT_INDEX.md` - the prune plan named that destination and
never created it). ROADMAP 85125 -> 41690 bytes, `test_doc_size_budget` was RED at HEAD
and is now green. 213 machine-generated reports archived. New `docs/adr/README.md` (adr/
was cited 29x with ZERO links). ADR-001 retired. RC_WORK_TRACKER resynced.

**LEDGER CITATION DEFECT (annotated, not repaired):** 387 of 1148 cited SHAs dead. NOT a
history rewrite - I claimed that first and it was WRONG (inferred from file position, which
maps to item number not date). Real shape: steady ~50 pct Apr-Jun, **0 of 537 in July** -
a worktree-slice citation convention that already self-corrected. Work landed; citations
were wrong. Preamble added to the 3 ledger docs.

**GATED SYNTHETIC TRIAGE: 6 of 124 closed, not "a lot".** 14 agents (7 triage + 7
adversarial refuters). CONFIRMED 15 / PARTIAL 24 / REFUTED 31. Dominant kill =
SUBSTITUTION. Two agents produced evidence that failed audit (fabricated build numbers;
3-of-880 sample published as a bound). **Do NOT re-pitch the synthetic drain** - header
carries the note. Real yield = 24 PARTIAL rewrites (live half is now a glance). 118 open.

NEXT: **Term A** archetype objective - `score_by="team_blended"` on ehp.py, DEFAULT-OFF,
gated on the ally-facing `affects` signal; moves 13 of a 28-champion cohort that currently
shares ONE byte-identical build order (Taric and Rammus get the same six items). Needs new
`_item_ally_grant.py`, ENGINE 1.220.0. **Do C1 FIRST:** re-adjudicate RM-92 at build depth -
Soraka/Yuumi "#10 of 10" are `item_ids=[]` ARTIFACTS (Moonstone is #2 at depth and the
shipped build order already buys it); 2 of 6 re-probed rows dissolved, so the 21-champion
figure is unaudited. Verification metric is CONTEXT LIFT (permutation test); pre-fix
baseline measures the engine as context-BLIND (MRR +0.0018, 42 pct placebo-identical).

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

