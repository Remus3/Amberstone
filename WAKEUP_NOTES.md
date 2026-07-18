# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the DS_SWEEP batch18 session relocated four blocks - the 2026-07-18b four-track session, the RM-81 staleness-detector session, and the batch15 + batch14 sweep sessions - to `docs/history_notes.md`; newest 3 = batch20 + batch19 + batch18; the 2026-07-18d four-track session was relocated by batch20).

---

# 2026-07-18g (DS_SWEEP batch20 -> 114/173: Rell / Renata Glasc / Renekton / Rengar / Riven; FIVE GAPs, zero REFUTEs, one live user-facing defect, one retraction)

Read-only research pass, NO engine change. LEDGER 939. Fan-out held a fifth session.
**First all-GAP batch of the sweep.**

**RM-90 IS A COHORT VERDICT AND IT IS THE HEADLINE - 12 of 14 support champions ship
exactly TWO build orders.** Verified against the shipped artifact
`data/daemon_slayer/16.14.1/build_orders_sr.json` (DISPLAY-keyed: the key is
`"Renata Glasc"` WITH a space):
- GROUP A byte-identical for Renata Glasc / Soraka / Janna / Nami / Lulu / Milio /
  Sona / Seraphine: Echoes -> Merc Treads -> Ardent -> Staff of Flowing Water ->
  Redemption -> Moonstone. ad_heavy / ap_heavy / balanced are identical too.
- GROUP B byte-identical for Bard / Taric / Rakan / Rell: Randuin's -> Merc Treads ->
  Warmog's -> Sterak's -> Jak'Sho -> Spirit Visage.
Renata's shipped items are 0.79-5.6% real pick and her core (Locket 69.5%, Imperial
Mandate 44.8%, Shurelya's 27.8%, Bandlepipes 25.5%) is ABSENT. Rell's are all 0-3%
and her core (Zeke's 70.6%, Locket 64.1%, Knight's Vow 28.3%) is ABSENT.

**Four layers of cause:** (1) `ds.hps` ranks a CLOSED 9-item pool
(`enchanter_only=True`) excluding Zeke's / Bandlepipes / Solstice Sleigh / Celestial
Opposition / Shurelya's / Vigilant Wardstone - `hps.py` ~894-907 documents this
itself; (2) inside the pool the order is champion-invariant (11 of 12 identical 9/9;
Locket 11.73, Knight's Vow 10.00, Mikael's 4.17 are CONSTANT for every champion);
(3) the tank route fails from the other side - self-EHP cannot value ally auras;
(4) the RF2 escape hatch is default-OFF **and** its table holds ONE champion, Rakan,
who no longer routes to `ds.hps` after Slice C - **so RF2 fires for nobody.**

**The uncomfortable part, stated plainly: the Alistar / Blitzcrank / Braum / Bard /
Rakan REFUTEs were too lenient.** The reasoning ("correct axis, builds no damage,
team-aura is a class-level scope limit") is still true but under-weighted the
outcome - they receive a shipped build order omitting their 60-70%-pick first
legendary. New standing rule now in the tracker: **do not rule another team-aura
support REFUTE without first checking its shipped build order against real pick
rates.** Filed as its own task, NOT fixed (pool widening is RC-2; RF2 is
operator-gated).

**Renekton - the most direct falsification of a scorer output yet: the engine's #1
pick is measurably his WORST item.** BotRK registers 4.2% pick at **48.0% WR, the
only sub-50% item on him**, while his 66.5% signature Eclipse is #10 behind nine
never-built items and Black Cleaver (60.6%) is #30. Also banked: **Eclipse lost
lethality in V14.1 and is now a BRUISER item** - do not read Eclipse-first as
lethality.

**Riven - the strongest RC-1 statement in the sweep, because the credited mechanic is
entirely real AND entirely unbuilt.** Runic Blade charged autos genuinely apply
on-hit, ARE crit-affected, apply lifesteal at 100%, and proc Spellblade cleanly - so
every precondition behind BotRK / Kraken / IE / Trinity is TRUE and players build none
of them (research named Trinity Force "the notable trap"). Whole top-10 never-built;
Axiom Arc #34 / Death's Dance #40 / Endless Hunger #41 buried. Cause is CADENCE not
mechanics - Q resets the attack timer, ability haste is the real stat, zero AS items
in her data.

**Rengar** adds the fourth corroboration (max Ferocity is **4**, not 5, so empowered Q
lands ~once per four casts; Umbral 73.3% at #13, Profane Hydra 70.9% at #38). With
Rek'Sai, Pantheon and Olaf that is **five kits that HAVE the term and must not be
credited at face value - the boolean-gate design for RM-86 L1 is now decisively
refuted.**

**RETRACTION - batch19's Opportunity finding was WRONG; the task chip is withdrawn.**
Opportunity (id 6701) was removed from SR in patch 26.09; `items.json` carries
`inStore: false` and `gold.purchasable: false`, and the map-30 alias 226701 is Arena-
only. The candidate filter was CORRECT. I asserted a defect from engine-side absence
alone without checking buyability or live-game existence - a straight violation of
verify-before-declaring-broken, caught by the Rengar research. Banked in the Rengar
verdict so it is not re-filed.

**NEXT:** Rumble onward (batch21); next GAP spec = RM-91. RM-86 L1 remains the
highest-value engine work; batch20 hardened its design (continuous, not boolean) and
RM-90 adds a second RC-2 workstream (the support pool) alongside Quinn's.

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
