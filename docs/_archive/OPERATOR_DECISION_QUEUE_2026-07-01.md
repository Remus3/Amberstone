# Operator Decision Queue - 2026-07-01

Companion to `docs/LIVE_GAME_GATED_SYNC.md`. Every item here needs an operator
choice (not a play session). Two buckets: DECIDE NOW (no game, no review) and
NEEDS REVIEW FIRST (a code/logic look or a consumer-wire before it is decidable).

Each row: what it is - PRO - CON - RECOMMENDATION. Work top to bottom next session;
the ones marked (I can execute) need only a yes and I do the rest headless.

Load-bearing fact: seam ground-truth is ZERO seams wired-on-live. So every DS
flip is gated behind either (a) an operator authorize for the already-validated
ones, or (b) a wire-then-review for the rest.

---

## 1. DECIDE NOW (no game, no review)

### 1A. Validated seam flips awaiting authorize

These 3 had their live eyeball DONE. The remaining step is a yes/no + (for DS
seams) a `:8893` restart. This is the lowest-risk, highest-closure bucket.

**D1. DSV5 `RC_COMP_HP_LEAN` -> default ON**
- WHAT: tank-heavy enemy comp scales `target_max_hp` up so AP DoT items
  (Liandry's) float vs tanks. Eyeball DONE 2026-06-23 (R24): SANER NOT DIFFERENT.
- PRO: closes THREE ledger obligations (R24 / 592 / 593) in one edit. No game.
  Validated safe - can only nudge Liandry's up, never reorder toward a worse pick.
- CON: it is a global coaching heuristic default; frozen-file edit (`ops/rc_supervisor.py`
  env) or machine env. Impact is narrow (only mage-scorer champs, only borderline
  Liandry's cases).
- RECOMMENDATION: **FLIP ON.** Cheapest closure on the board; already validated.
  (I can execute: machine-env `RC_COMP_HP_LEAN=1` + RC-Supervisor restart.)

**D2. DSP11 kit-axis flip (C4)**
- WHAT: 7 WIN-anchored champs surface kit-axis winners (Pyke Opportunity/Youmuu's,
  Nilah IE/Navori, Ezreal Trinity/Muramana). LIVE-VALIDATED 2026-06-17, FLIP-READY.
- PRO: lethality + crit + negative-control (Caitlyn byte-identical) all eyeballed.
  Wiring is transport-ready; flip is a one-line default + DS restart.
- CON: the Ezreal/Corki manamune sub-case was not separately eyeballed (low risk -
  same table, same mechanism). Needs a DS `:8893` restart.
- RECOMMENDATION: **FLIP ON.** Validated both sub-cases + negative control. The
  manamune residual is optional polish, not a blocker.

**D3. RF1 bruiser survivability flip (C5)**
- WHAT: 9 tabled bruisers float buried survivability winners (Darius Force of
  Nature/Sterak's, Udyr Jak'Sho). LIVE-VALIDATED Yasuo 2026-06-18, FLIP-READY.
- PRO: eyeballed SANER on Yasuo; non-tabled bruiser (Garen) byte-identical.
- CON: only 1 of 9 tabled bruisers eyeballed. Slightly thinner evidence than
  DSP11. DS restart on flip.
- RECOMMENDATION: **FLIP ON, or roll 1-2 more (Darius/Udyr) in an ARAM first if
  you want more confidence.** The mechanism is float-by-WIN-membership (adds EHP,
  never DPS) so it structurally cannot reorder toward a worse pick - I lean FLIP.

### 1B. Heuristic / behavior calls (your judgment, no game)

**D4. HZ-A choice-B even<->hold band flip**
- WHAT: laning-coach band adjustment, +57 ticks quantified, [HOLD], not applied.
- PRO: quantified benefit already measured.
- CON: operator-gated because it changes the served laning call cadence; you may
  prefer the current band feel.
- RECOMMENDATION: **APPLY** unless you have a feel-based reason to keep the current
  band. The +57-tick delta is measured, not speculative.

**D5. DS target-current-HP% / enemy-pen product-call flips**
- WHAT: whether DS should chase target-current-HP% and enemy-penetration product
  interactions. [HOLD]. This is a PHILOSOPHY call that gates the C9/B20 eyeballs.
- PRO: unlocks a batch of downstream pen-aware EHP eyeballs (C9).
- CON: "off-meta chase" - adds complexity for situational accuracy that may not
  move the served build often.
- RECOMMENDATION: **DECIDE THE PHILOSOPHY FIRST** (chase situational accuracy: yes/no).
  My lean: YES but low priority - it only matters vs real enemies carrying real pen,
  so it rides a real-SR/ARAM game anyway. Answer it before booking C9.

**D6. R2 carry-efficiency grade fold default-ON re-baseline**
- WHAT: fold a carry-efficiency grade into the default; computable over the
  existing rewind corpus.
- PRO: no game needed, corpus already present.
- CON: re-baselines a grade surface - changes displayed numbers.
- RECOMMENDATION: **RE-BASELINE + eyeball headless, then flip.** Low risk.

**D7. WP-F4a ward-stack keep-vs-retire**
- WHAT: keep or retire the ward-stack feature.
- PRO: retire path is fully headless (clean removal).
- CON: KEEP is likely infeasible - Match-V5 carries NO ward positions, so the
  feature cannot be fed live data.
- RECOMMENDATION: **RETIRE.** The data to support KEEP does not exist upstream.

**D8. item 211 seven residual orphan rows** (1640/1633/1519/1518/1517/1506/1487)
- WHAT: per-row keep/drop decision on 7 orphaned rows; needs live RC + Riot key,
  no game.
- PRO: closes a long-standing data-hygiene tail.
- CON: requires a per-row judgment (7 small calls).
- RECOMMENDATION: **let me pull the 7 rows live next session and present each with
  a keep/drop rec** - then you approve in one pass.

**D9. DS cross-eval A/B/F2 rewind-WIN validations**
- WHAT: residual gate on the cross-eval harness = an operator decision (harness
  exists, runs over rewind_history.db).
- PRO: headless, harness already built.
- CON: needs you to accept the harness verdict as sufficient (vs a live eyeball).
- RECOMMENDATION: **ACCEPT the harness as the validation surface** for A/B/F2 -
  these are corpus-WIN checks, not pixel checks; a live game adds nothing.

### 1C. Housekeeping

**D10. ARENA NEEDED: YES - queue one Arena game, or accept 8 items parked forever**
- WHAT: 8 items (D1-D8 in the sync doc: 6x3 capture, set_augment_intent probe,
  boots visual, apply_mode_modifiers re-rank, state-debounce flip, augment/anvil
  shadow SEEDING, Arena PGR, +1 PBE HOLD) are Arena-only. Your prefs say avoid Arena.
- PRO of queueing: closes 8 items that cannot close any other way.
- CON of queueing: one Arena game you would rather not play; several of the 8 are
  low-value (shadow seeding, visual confirms).
- RECOMMENDATION: **one Arena game eventually, low priority.** Not this cycle unless
  you feel like it. If you decide NEVER, I will mark all 8 [PARKED - operator declined
  Arena] so they stop showing as open drain items.

**D11. 15 archive-candidate .md moves -> docs/_archive/**
- WHAT: 15 stale/one-shot docs (DISTRIBUTION_LAYOUT, LAUNCH_STRATEGY, Peer artifacts,
  done audit baselines, etc.) + the whole dead `docs io RC peer/` dir as a wider candidate.
- PRO: de-clutters ripgrep + the doc tree; all are superseded/complete.
- CON: none material (archive keeps them, force-tracked; links updated on move).
- RECOMMENDATION: **APPROVE the moves.** (I can execute: git mv + link fixups.)
  The `docs io RC peer/` whole-dir move needs a separate yes (wider scope).

**D12. 18 stale-row doc fixes** (ROADMAP/README/ARCHITECTURE/OPERATIONS/BACKLOG/etc)
- WHAT: relocate-only / mark-done edits for drifted rows (shipped PGR reframe still
  listed pending, stale DS counts, retired-machine prose, stale commit hashes, etc).
- PRO: keeps the living docs honest; all are relocate-or-correct, no behavior change.
- CON: README DS-count refresh is a DS-batch job (do NOT recompute coverage in a
  general sync) - that sub-item stays deferred.
- RECOMMENDATION: **APPROVE the relocate-only fixes** (I can execute), EXCLUDING the
  README DS-count recompute which rides the next DS batch.

---

## 2. NEEDS REVIEW FIRST (not decidable until reviewed / wired)

### 2A. Code-logic review (possible BUG)

**R1. Comp-verdict soundness - Vex->Garen reads INVERTED**
- WHAT: the ARAM comp-verdict renders "all-AD comp - mix damage type" in a case
  that looks logically inverted. Review `core/aram_comp_verdict.py`.
- WHY REVIEW FIRST: if it is a real inversion it is a served-coaching BUG, not a
  flip decision. Headless, not game-gated.
- RECOMMENDATION: **schedule a root-cause-fix review next session** (TDD: failing
  test that reproduces the inverted verdict, then fix). Highest-value item in
  bucket 2 because it may be a live wrong-advice bug.

### 2B. Producer-only seams - need a consumer WIRED before any live test

These read as "shipped" in the ledger but CANNOT be live-validated because no live
surface calls them. The review = decide WHICH consumer surface wires each, then it
becomes an eyeball item.

**R2. DSP5 (summoner) / DSP6 (enemy runes) / DSP7 (ally aura) / P3.2 (`compute_antitank_live`)**
- STATE: producer + tests only; zero live consumers. `/anti-tank` still calls the
  STATIC path.
- REVIEW NEEDED: pick the consuming surface (fight_report / matchup / a coach /
  survivability-draft) for each, wire it, THEN eyeball live.
- RECOMMENDATION: **batch a "wire the DSP5-7 + P3.2 consumers" headless session**
  before the next real-SR game so they are testable when you play.

**R3. R50/R51/R53 (K'Sante all-out / target-hp / caster-hp gates) + R9/R12/R30/R41 family**
- STATE: engine seams, default-OFF, no live consumer.
- REVIEW NEEDED: these need a per-instant scenario / fight_report consumer (gating
  a whole burst on one HP snapshot is a stepped-eval use, not a blind flip).
- RECOMMENDATION: **defer** - lower value than DSP5-7. Wire only if/when a
  scenario-eval surface is built. Do NOT flip blind (charter 4b).

**R4. Phase-D (`apply_passive_damage` / non-every-AA on_hit / `assumed_stacks`)**
- STATE: no RC-side caller can even flip `apply_passive_damage`; `assumed_stacks`
  needs a live stack-count feed that does not exist.
- RECOMMENDATION: **defer** until a live stack-count feed exists. Not actionable now.

### 2C. Validation-path reviews (try headless first - may de-gate entirely)

**R5. Same-state Haiku-skip fidelity proof**
- REVIEW: try replay/logged-state validation FIRST; only fall back to the live
  C14/D5 rows if logs prove insufficient.
- RECOMMENDATION: **attempt headless (replay) next session** - likely de-gates two
  live rows.

**R6. champ_select pickban-DB flip counter-quality** - validate headless vs the
  rewind corpus. RECOMMENDATION: **headless, schedule with R5.**

**R7. ability_hps v2 wiring** - validate vs real enchanter build data in the rewind
  corpus. RECOMMENDATION: **headless, schedule with R5.**

---

## 3. Recommended order for next session

1. **DSV5 flip ON** (D1) - one edit, closes 3 obligations. (I execute on yes.)
2. **DSP11 + RF1 flips ON** (D2/D3) - validated, DS restart once for both.
3. **Doc housekeeping** (D11 archive + D12 doc fixes) - I execute on yes, cheap.
4. **Comp-verdict bug review** (R1) - root-cause-fix; may be live wrong advice.
5. **Wire DSP5-7 + P3.2 consumers** (R2) - unblocks the next real-SR eyeballs.
6. **Headless validation attempts** (R5/R6/R7) - may de-gate live rows.
7. **Behavior calls** (D4-D9) - answer as you go; most are low-risk yes.
8. **Arena decision** (D10) - park or queue; your call, low priority.

Items 1-3 alone clear ~35+ open rows / obligations with no game and minimal risk.
