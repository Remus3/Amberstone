# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the DS_SWEEP batch18 session relocated four blocks - the 2026-07-18b four-track session, the RM-81 staleness-detector session, and the batch15 + batch14 sweep sessions - to `docs/history_notes.md`; newest 3 = batch19 + batch18 + the 2026-07-18d four-track session; the 2026-07-18c two-track session was relocated by batch19).

---

# 2026-07-18f (DS_SWEEP batch19 -> 109/173: Pyke / Quinn / Rakan / Rammus / Rek'Sai; 4 GAP + 1 REFUTE, TWO new numbers, and one champion that breaks the RM-86 L1 plan)

Read-only research pass, NO engine change. LEDGER 938. Qiyana skipped (already
FENCED). **Fan-out held for the fourth session running**: probes main-thread, 5 flat
research agents with a hard no-sub-agent constraint, zero nested spawns, zero kills.

**QUINN RM-89 IS THE ONE THAT MATTERS - she breaks the L1-only plan.** First champion
measured carrying BOTH RM-86 root causes at once:
- **RC-1**: carry/ds.dps leads BotRK #1 / Runaan's #2 / Kraken #3 / Stormrazor #4, every
  one 0-2% real pick, because **Harrier is priced as attack-speed throughput when its
  proc rate is cooldown-gated and attack-speed-INDEPENDENT**, and crit chance is a
  cooldown scalar that does NOT make it crit. No reroute rescues her - all four routes
  still lead BotRK #1.
- **RC-2**: her carry pool holds only **111** items and **structurally excludes Profane
  Hydra and Umbral Glaive**, both present in the 144-item assassin/onhit/bruiser pools.
  Her #2 signature item is not in the ranked set at all.
So **a perfect L1 gate would suppress her three bad leads and still never surface her
real second item.** Section 5 predicted L1 makes RC-2 worse; Quinn is the instance. The
spec's sequencing note now reads: **L1 is necessary and provably insufficient.** Also:
her role FLIPPED to jungle ~55% / top ~32% (16.10-16.11 Harrier monster damage, 16.14
Harrier CD cut) and she is a lethality assassin in ~85-90% of real builds, ~0% on-hit.

**Rammus displaces Ornn as RM-87's canonical example.** ds.ehp is close to rank-INVERTED
for him: his **92%-pick effectively-mandatory Thornmail is #20** while **three items under
1.6% combined pick sit #2/#5/#9** (Warmog's 0.35%, Heartsteel 0.85%, Spirit Visage 0.33%).
Measured mechanism: passive Spiked Shell = 15% TOTAL armor + 15% TOTAL MR as bonus AD; W
turns armor A into 1.6A+47 at rank 5 so passive AD = 0.24A+7, **about +24 AD per 100
armor**; **bonus HEALTH contributes ZERO to every damage source in his kit**. A self-EHP
objective rewards health at high resist values, so it pushes toward exactly what real
players avoid.

**Pyke RM-88 - new shape: a throughput objective cannot price a discontinuous execute
threshold plus a gold-and-reset economy.** Lethality QUADRUPLE-dips for him (damage, E
stun duration, W move speed, R execute threshold at 1.5 per lethality, passive grey-health
rate); the engine models only the damage dip. ds.burst leads never-built BotRK #1 /
Trinity #4 / IE #7 over his real Umbral #12 / Youmuu's #15 / Edge of Night #19. **Route is
CORRECT, do not re-open** - `axis_correct_archetype` catches the Support tag, live-
confirming that Pyke was never broken. **Correction recorded so it is not re-derived:** his
bonus-health-to-AD passive is NOT exploited (gold-neutral, zero durability, strictly
dominated); the load-bearing coupling runs the OTHER way - grey-health cap = 80 + 800%
bonus AD, so buying AD buys effective HP.

**Rek'Sai - third corroboration that L1's vector must be CONTINUOUS, not boolean.** Her
unburrowed Q genuinely applies on-hit AND crits and she genuinely wants attack speed, yet
her ds.hybrid top-9 is entirely never-built and her 67.1%-pick Spear of Shojin sits
**#48** - because Q is only 3 empowered autos per Fury cycle. With Pantheon (~1/5 cadence)
and Olaf (free kit AS) that is three kits that HAVE the term and must still not be
credited at face value.

**Rakan REFUTE doubles as the first post-hoc validation of a Slice C route override** - the
RM-84 enchanter -> tank move is confirmed at roughly 10:1 (durability ~167% combined
across slots vs ~16% for the whole heal/shield shelf). Flagged honestly as the WEAKEST
refute in the Braum/Alistar class: his two real first legendaries are #16 and #23.

**The invariance measurement, redone at scale (32 champs, 4 scorers, 8 per panel, 28 pairs
each, top-8):** `ds.ability` **8.00/8 set overlap - perfectly invariant, all eight mages
get the same eight items**; `ds.ehp` 7.57/8; `ds.hybrid` 6.04/8; `ds.dps` 4.54/8. Replicates
RM-86 section 2's ordering independently on a panel 4x larger, plus a refinement: **ds.dps
does not vary continuously, it BIFURCATES** into an on-hit-led cluster (Quinn/Vayne/Sivir)
and a lethality-crit cluster (Jinx/Caitlyn/Draven) - which is exactly how Quinn ends up
served an on-hit list.

**A data-layer bound on ANY scorer fix:** three of five champions carry their decisive
mechanic in `effects_descriptions` prose with **EMPTY `damage_blocks`** (Rammus armor->AD,
Pyke health->AD, Quinn Harrier) - RM-81 intersecting RM-86. For them the conversion an L1
gate would read is not in the data at all, so L1 cannot reach them by any design. An L1
acceptance suite should carry one as a known-unreachable control.

**Filed as its own task, NOT fixed:** the legendary **Opportunity** (id 6701, 2700g) is in
the item catalog but enters **ZERO** ranked pools across 7 champions and 2 archetypes,
while sibling lethality items appear normally. RC-2 pool-membership defect.

**Process note:** I hit both traps in my own batch18 COUNT INTEGRITY note - a naive
`split('## Full roster')` grabbed the prose mention, and a multi-line replace across the
now-non-contiguous Summary lines silently no-opped. Caught only because the count was
re-verified AFTER writing. The note now documents both.

Artifacts: 5 verdicts + 1 method note in `docs/DS_SWEEP_TRACKER.md`; new **section 9** in
`docs/specs/RM-86_scorer_kit_blindness_investigation.md`; 5 `project_ds_sweep_*` memories.

**NEXT:** Rell onward (batch20); next GAP spec = RM-90. **RM-86 L1 is still the highest-
value engine work, now with acceptance anchors AND a proven insufficiency bound - the
honest framing is L1 + RC-2 pool work, not L1 alone.**

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
