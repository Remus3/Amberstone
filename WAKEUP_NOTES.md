# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-18 (the batch21-25 sweep session relocated the batch19 block `2026-07-18f` to `docs/history_notes.md`; newest 3 = the batch21-25 sweep session `2026-07-18i` + the RM-86 L1 engine session `2026-07-18h` + batch20 `2026-07-18g`). NOTE: `scripts/wakeup_prune.py` is a silent NO-OP against these headers - its `SESSION_RE` requires a word boundary after the day, so a letter-suffixed header like `# 2026-07-18h` never matches and it reports "nothing to do" at any file size. Relocations are manual until that is fixed (filed as its own task).

---

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
