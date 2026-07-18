# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the RM-86 L1 session relocated the batch18 block `2026-07-18e` to `docs/history_notes.md`; newest 3 = the RM-86 L1 engine session `2026-07-18h` + batch20 `2026-07-18g` + batch19 `2026-07-18f`). NOTE: `scripts/wakeup_prune.py` is a silent NO-OP against these headers - its `SESSION_RE` requires a word boundary after the day, so a letter-suffixed header like `# 2026-07-18h` never matches and it reports "nothing to do" at any file size. Relocations are manual until that is fixed (filed as its own task).

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
