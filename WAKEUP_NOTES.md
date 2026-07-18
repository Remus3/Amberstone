# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the DS_SWEEP batch18 session relocated four blocks - the 2026-07-18b four-track session, the RM-81 staleness-detector session, and the batch15 + batch14 sweep sessions - to `docs/history_notes.md`; newest 3 = batch18 + the 2026-07-18d four-track session + the 2026-07-18c two-track session).

---

# 2026-07-18e (DS_SWEEP batch18 -> 104/173: Olaf / Orianna / Ornn / Pantheon / Poppy; 4 GAP + 1 REFUTE, but only ONE new number)

Read-only research pass, NO engine change. LEDGER 937. **Fan-out held for the third
session running**: every engine probe in the main thread, exactly 5 flat research
agents each opening with a hard no-sub-agent constraint. Zero nested spawns, zero
limit kills. DS confirmed live at ENGINE 1.217.0 / patch 16.14.1 BEFORE any probe.

**The convergence from batch17 repeats, harder.** Four GAPs and only one needs a new
spec number: Olaf + Pantheon are the Aatrox RM-39 ability-bruiser family, Orianna is
the Ahri RM-40 burst-mage family (sixth champion). RM-87 goes to Ornn alone. The sweep
is now mostly confirming known families rather than finding new defects - that is a
signal about where the remaining value is (fixing RM-86 L1, not finding RM-88).

**Olaf is the most extreme RM-39 instance measured.** bruiser/ds.hybrid returns a top-6
where EVERY item is one he essentially never builds (BotRK #1 <2%, Trinity #2 <2%,
Kraken #4 ~0%, Heartsteel #9 ~0%, Liandry's #20 on a champ with ZERO AP ratios), while
his entire real core sits #19-#43 with signature **Stridebreaker #33**. No reroute
rescues him. Nuance that stops it being plain on-hit blindness: his W grants 50-90% AS
and his passive up to 70% missing-HP AS, so the kit DOES scale with attack speed - the
AS just arrives FREE, so purchased AS has sharply diminishing real value.

**Pantheon supplies the numeric anchor RM-86 L1 was missing.** Only his empowered W can
crit or apply on-hit and the passive empowers ~1 ability per 5-cast cycle, so AS/crit/
on-hit convert at roughly a FIFTH of face value. The meta researcher reached RC-1's
conclusion unprompted, without seeing the spec. **This argues L1's conversion vector must
be CONTINUOUS in [0,1], not the boolean has-an-AS-term gate section 4 sketched** - a
boolean scores his on-hit at 0 or 1 and both are wrong.

**Orianna splits a standing family belief in two.** Engine leads Liandry's #1 at a 3.3%
real pick rate and buries her signature Luden's Echo #13 (GAP, textbook). BUT Blackfire
Torch #2 is NOT a defect - it is genuinely 31%-pick meta that OUT-WINS Luden's, bought
for AP/haste/mana rather than a burn her kit cannot apply. **The "Liandry's + Blackfire
lead" is TWO findings, not one.** Every future burst-mage verdict and any L1 acceptance
test must score them separately or the gate over-fires.

**RM-87 (Ornn) is the one genuinely new shape: the first ds.ehp gap that is an intra-pool
WEIGHTING defect, not an omitted off-axis core.** He builds zero damage items so tank/
ds.ehp is the CORRECT axis (NOT the Amumu RM-44 / Cho'Gath RM-51 / Galio RM-55 shape -
there is nothing off-axis to omit). But four sub-7%-pick items rank above his signature
Sunfire Aegis #11 (Warmog's #2 at 1.9%, Heartsteel #5, Spirit Visage #8 at 1.0%, Dead
Man's #10 at 1.7%), with Thornmail #20. Root cause MEASURED: **E Searing Charge scales
off 40% bonus armor + 40% bonus MR** and passive Living Forge inflates that same resist
pool +10-30%, so resists pay TWICE while a self-EHP objective counts them once.

**THE BATCH HEADLINE - the Ornn / Poppy matched pair, and what it proves.** Both route
tank/ds.ehp and return the SAME top-6 in the SAME order. That invariance is CORRECT for
Poppy (REFUTE: her real core occupies #6/#8/#9/#10, never-built items correctly
suppressed at BotRK #73 / Liandry's #50 / Trinity #47, and decisively **no Poppy ability
converts her own bonus HP or resists into damage** - Q reads the TARGET's max HP) and a
DEFECT for Ornn. **This extends the RM-86 section-2 invariance table from top-5 to top-8
on two more scorers:** Ornn / Pantheon / Poppy rerouted to bruiser return an identical
top-8 item SET (Ornn and Poppy 8-of-8 in ORDER) across a tank, a tank/fighter and an
assassin/fighter - **and Olaf is the control that names the mechanism**, overlapping only
4-of-8 because his base AD/AS differ. That is RC-1 as a POSITIVE measurement rather than
an absence: the champion enters the objective through BASE STATS ONLY, so similar base
stats yield literally the same build.

**Standing rule now in the tracker:** adjudicate every ds.ehp and ds.hybrid verdict on
whether the SHARED list happens to fit the champion, never on the list being
champion-specific - it is not. (Companion to the batch16 ds.hps invariance finding.)

Artifacts: 5 verdicts + 2 method notes in `docs/DS_SWEEP_TRACKER.md`; new **section 8**
in `docs/specs/RM-86_scorer_kit_blindness_investigation.md` (batch18 corroboration + 5
concrete per-champion L1 acceptance anchors, including Poppy/Ornn as negative controls);
5 `project_ds_sweep_*` memories.

**NEXT:** Pyke onward (batch19); next GAP spec = RM-88. **RM-86 L1 is still the
highest-value engine work on the board and now has per-champion acceptance anchors** -
that is the recommended next build, not batch19. Ornn RM-87, Nunu's TANK-tag route gap
and Nasus's RC-2 pool partition are operator-gated and unstarted.

---

# 2026-07-18d (FOUR TRACKS, all four SHIPPED: 16.14 re-extract + strict ON, batch17 -> 99/173, RM-84 fixed, RM-86 spec answers the Vayne question)

All four operator tracks completed. LEDGER 936. **Fan-out held**: engine probes in the main thread, exactly 2 flat research agents with a hard no-sub-agent constraint, zero nested spawns, zero limit kills.

**T1 - re-extract + strict flip DONE.** 23 champions / 58 fields moved 16.11 -> 16.14 (NOT the 49/75 in the brief - that was the blast radius of DROPPING the sidecar, a different measurement). Biggest: Kaisa R shield [70,170] -> [100,350], LeBlanc R [140,840] -> [140,940], Orianna R [250,1000]@95%AP -> [225,850]@110%AP, Senna Q heal 50% -> 35% AP, Varus Q 150% -> 120% AD. After re-extract the payload patch matches the directory, so **strict is a no-op on shipped data** - it only bites on a future copy-forward. ENGINE 1.216.0 -> 1.217.0. BACKLOG entry deleted.

**T3 - RM-84 SHIPPED, but the briefed fix path was wrong twice.**
1. **`data/cs_archetype_picks.json` is GITIGNORED** (`.gitignore:77`). An override there reaches neither CI nor the Share mirror nor any other machine, and re-creates the pollution vector LEDGER 824 removed the UI for. Shipped instead as **Slice C** - git-tracked `core/ds_support_route_overrides.{json,py}`, mirroring the Slice A/B roster precedents.
2. **Pyke and Senna were never broken.** `axis_correct_archetype` already catches them (AD kit vs AP enchanter is exactly the conflict it resolves). The misroute only survives when the target is AP or axis-neutral.
Adjudicated all 18 per champion: **5 overridden** (Morgana -> mage; Thresh/Rakan/Taric/Bard -> tank), 9 already correct, 2 correct via axis correction, **2 HELD as unrepresentable** (Renata Glasc, Zilean - flipping either swaps one never-build violation for another; Zilean's real build has Liandry's/Luden's/Malignance/Rylai's ALL absent).

**T3 backfill found an unrelated live defect.** Regenerating both build-order tables and drift-guarding by re-running with Slice C removed attributed the diff cleanly: **5 champions to Slice C, 11 to PRE-EXISTING drift** (Akali/Diana/Ekko/Evelynn/Fizz/Katarina/LeBlanc = the Slice A roster; Gwen/Kayle/Kog'Maw = Slice B; + Locke). **The committed tables were never regenerated after Slice A/B routing shipped (LEDGER 911).** The precompute had been serving MAGE builds for the AP-assassins and pre-on-hit builds for Gwen/Kayle/Kog'Maw for two days. Fixed. Also caught a **forged stamp** my own blanket version bump created - it rewrote `engine_version` inside 6 generated JSON tables that had not been regenerated; both tables were then genuinely regenerated so the stamp is true. **Watch for this on every future ENGINE bump: a literal-replace sweep will silently re-stamp generated data.**

**T2 - batch17, 94 -> 99. Five GAPs, no REFUTEs** - and that is itself the finding: four are the SAME gap. Neeko / Nidalee / Nocturne [GAP RM-86, routes correct, item order is the archetype template], Nilah [GAP RM-86 + ROUTE, worst in batch - engine offers **Heartsteel and Liandry's to a crit marksman**, and the `carry` reroute does NOT rescue her, so a route-only fix cannot close it; the kit-axis INERT entry is CONFIRMED still inert - bruiser is already AD so there is no conflict to resolve], Nunu [GAP ROUTE - routes tank while `kit_damage_axis` returns **ap**; the engine identifies the kit correctly and declines to act because tank is axis-NEUTRAL by contract. Liandry's is a genuine real-meta core for him and is unreachable from the tank pool. NOT auto-flipped - extending Slice C to TANK-tag misroutes is its own operator-gated call]. **Correction: Nocturne IS in the re-extract delta** (Q base [65,290] -> [65,265]); verdict unaffected, and it was measured after T1 landed.

**T4 - RM-86 spec: `docs/specs/RM-86_scorer_kit_blindness_investigation.md`. PARTIAL unification (3 of 4), and THE VAYNE QUESTION IS CLOSED.**
- **Vayne, answered two ways.** `ds.dps` does not model Silver Bolts *as stat-independent* - it does not model it **at all**. `dps.py` never imports `abilities` and contains no `damage_blocks`. Sweeping target_max_hp 1200/2500/5000: **only BotRK moves (70 -> 120 -> 217)**, because BotRK carries its own %maxHP term; Runaan's/Kraken/Stormrazor are flat. Tank Vayne is unrepresentable regardless of item filters. **Do not carry this a fourth time.**
- **The standing read is REFUTED IN BOTH DIRECTIONS.** 30 probes, mean top-5 overlap: `ds.ehp` 5.0/5, `ds.ability` 5.0/5, `ds.hps` 5.0/5, `ds.hybrid` 4.5/5, `ds.burst` 2.8/5, **`ds.dps` 2.2/5**. Mages/tanks/enchanters are the MOST invariant, not clean; `ds.dps` is the LEAST invariant, not the sole fault. Every AP champ gets Liandry's > Blackfire whether or not the kit has a DoT (Syndra and Veigar have none).
- **RC-1** (Naafiri + ds.hps + Vayne): scalar-objective greedy argmax, champion enters as STATS ONLY, no kit-conversion term - an item can raise the score through a stat the kit has no ratio for. Key proof: `ability_dps.py` reads `damage_blocks` 11 times and is STILL 5.0/5 invariant, while `dps.py` reads it zero times and is 2.2/5. **Kit-awareness at the compute layer does not imply it at the ranking layer.** So "make the scorers read the kit" is NOT the fix.
- **RC-2** (Nasus, does NOT unify): candidate-pool partition. The right items are not in the set being ranked - structurally the inverse of RC-1, and an RC-1 conversion gate makes it slightly worse. Its own spec, do not fold.
- Spec carries an L1/L2/L3 fix ladder with per-layer blast radius, a recommended sequencing (L1 default-OFF first, then L2 for `ds.hps` alone, then re-measure), and **three explicit REFUTE conditions** so a later session can attack it cheaply. The invariance table is the regression baseline.

**/done found two changelog gaps and closed them.** `Share/CHANGELOG.md` had no entry for 1.216.0 OR 1.217.0, and `agents/daemon_slayer/CHANGELOG.md` had none for 1.217.0 - so the seventh scorer shipped two days ago with no release note anywhere in the external package. Backfilled both. Also fixed the semantic drift the anchor auto-rewrite cannot see: **five places still said "six archetype scorers"** (README x2, 01_OVERVIEW heading + table, 02_FUNCTION_REFERENCE, 04_GAPS_AND_ROADMAP) and the on-hit row was missing from the 01_OVERVIEW scorer table entirely. Lesson for the next DS bump: `ds_share_sync.py --check` going green means the MIRROR and the version ANCHORS are fresh - it says nothing about prose, and prose is where the rot was.

**NEXT:** Olaf onward (batch18); next GAP spec = RM-87. RM-86's L1 is the highest-value engine work on the board and is now specced. Nunu's TANK-tag route gap and Nasus's RC-2 pool partition are both operator-gated and unstarted.

---

# 2026-07-18c (both tracks SHIPPED: P0 sidecar guard + DS-sweep batch16 -> 94/173; two findings that outlive the batch)

Ran the two operator-directed tracks. **Both completed.** LEDGER 935. Commits `4cd3c4c6` (P0, Tier-2) + `c7208965` (batch16).

**Fan-out cap held.** Engine probes ran in the main thread; exactly 3 flat research agents (Morgana / Nami / Nasus meta), each prompt opening with a hard no-sub-agent constraint. Zero nested spawns, zero session-limit events. The prior session's failure mode did not recur.

**TRACK 1 - P0 `task_d665f88b` SHIPPED.** Guard is in and the silence is over. Beyond the reported bug I found the ROOT CAUSE of the copy-forward: `tools/daemon_slayer_cdragon_ratio_extract.py` was **missing from the `docs/OPERATIONS.md` "Data extractors (full list)" table** while its sibling `cdragon_spell_extract` was listed - which is exactly why one artifact gets re-extracted per patch and the other does not. Added + marked ENGINE INPUT.
- NEW `cdragon_sidecar_patch()` probe + unconditional WARNING on payload-vs-directory patch mismatch + `AbilitiesSnapshot.load(strict_cdragon_patch=False)` hard-drop seam. 10 tests, RED first.
- **strict is OFF by design.** MEASURED: dropping the stale sidecar moves **49 of 171 champions (55 blocks / 75 fields)**. That belongs with the 16.14 re-extract as one diffed change, not smuggled in beside a doc fix. Filed in BACKLOG with the number.
- Live-verified: non-strict warns + applies Lux Q 75% AP (the 16.11 value); strict warns + falls back to Meraki 65% - exactly the item-320 re-pin pair.
- **The briefing was slightly off on one anchor:** `BACKLOG.md:11` carries NO stale default-OFF claim (grep-verified). Corrected the ones that do: `abilities.py` 82+700, `ds_wiki_staleness_check`, WAKEUP, 2 test headers.
- Sibling sweep: `cdragon_ability_ratios` + `cdragon_ratio_drift` are the ONLY two artifacts stale at 16.11.1; drift is tools-only (zero engine reads). Six artifacts carry no patch field at all = latent same class, logged.

**TRACK 2 - batch16 DONE, 89 -> 94.** Morgana [GAP RM-84], Naafiri [GAP RM-83], Nami [REFUTE], Nasus [GAP RM-85], Nautilus [REFUTE]. Next up **Neeko**, next spec **RM-86**. Full three-line convergence per champion in `docs/DS_SWEEP_TRACKER.md`.
- **Morgana RM-84** is the cheapest real fix on the board: her engine #2/#3 items (Ardent Censer, Staff of Flowing Water) have a literal **0.00% real pick rate at every depth in every role**, and the `mage` reroute ALREADY returns the correct build. Root cause is one tag lookup - DDragon `["Support","Mage"]` + `tag_to_archetype("Support") == "enchanter"`. **All 20 Support-tag-first champions route to enchanter, including Pyke, an AD lethality assassin.** Fix path = the existing but **EMPTY** `data/cs_archetype_picks.json`. Operator-gated, NOT auto-flip.
- **Nasus RM-85 inverts the standing framing:** he is a **JUNGLER at 55.6%** with Protoplasm Harness 59.98% first. His real build spans the bruiser and tank pools and NEITHER route can express it.

**TWO FINDINGS THAT OUTLIVE THE BATCH - read before the next sweep session:**
1. **The standing `item_ids=[]` probe under-ranks AMP-ONLY items.** An amp multiplies throughput an empty build does not have. Moonstone on Nami: 0.4 empty -> 11.0 -> 12.9 -> 14.9, moving 9th to 2nd; Redemption 6th to 1st. I caught this mid-session and re-probed Naafiri at four depths before banking her GAP (it held). **Prior enchanter verdicts banked on empty-build probes should be re-checked at depth.**
2. **`ds.hps` item ranking is champion-INVARIANT.** Ten enchanters, identical order, every depth and target state, deltas within 0.6. The engine DOES compute per-champion heal/shield throughput (Soraka 10.21/s vs Morgana 2.52/s) but `apply_ability_hsp_amp` - the seam that would let that weight items - exists only on `compute_hps` and is absent from `rank_items_by_hps` AND the dispatcher. **So adjudicate enchanter verdicts on the ROUTE, not the item order.** Memory `project_ds_hps_champion_invariant`.
Also: **`ds.hybrid` emits NO `delta` key** (`delta_dps`/`delta_ehp`/`hybrid_delta_pct`) - a probe reading `delta` silently gets 0.0 per row while rank order stays valid. The probe recipe in the operator brief lists `delta` as a RankedItem key; that is true for burst/ehp/hps/ability, not hybrid.

**STILL OPEN - the Vayne question, unchanged.** Whether `ds.dps` models Silver Bolts as stat-independent is still unprobed; the operator flagged it as their call, not a task, and did not call it this session. Worth noting the batch found the structurally identical case in `ds.hps` (finding 2 above), which makes the Vayne probe more valuable, not less: if a scorer cannot represent a kit, that is a finding about the scorer.

**NEXT:** Neeko onward (RM-86). The three batch16 GAPs are all operator-gated fixes, not auto-flips.
