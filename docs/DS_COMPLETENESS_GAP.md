# Daemon Slayer - Completeness Gap Analysis

> **SNAPSHOT as of 2026-06-19 - the live-count lines below are SUPERSEDED.** Live DS engine
> is 1.184.0 now (not 1.147.0), and several gated boxes have since flipped (B45/B46/B47,
> DSP11 C4). Do NOT read the counts in this file as current - see docs/LEDGER.md and
> docs/LIVE_GAME_GATED_SYNC.md for live state. This doc is a dated snapshot, kept in place
> (not archived) because it is cross-referenced by line number.

> Authored 2026-06-19 (RC 2.0 Phase 8.2). Answers the operator question: "What is
> lacking for Daemon Slayer to be TRULY complete - nothing more to add or do, even
> the smallest things, besides patch updates?" Honest verdict: a build/combat engine
> over a live, balance-patched game is never 100% "done" - the target meta moves every
> patch and Riot ships new kits. But the set of GENUINELY-OPEN additive gaps is now
> small and enumerable, and most of it is operator-gated live-validation, not new code.
> All counts below are verified live (see section 1), not recalled from docs.

---

## 1. LIVE STATE (verified)

Probed `GET http://127.0.0.1:8893/health` (the DS server speaks plain HTTP on :8893,
not HTTPS - a `curl -k https://` returns empty / TLS WRONG_VERSION_NUMBER; use `http://`):

```
{"status":"ok","engine_version":"1.147.0","patch":"16.12.1","champions":172,"items":706}
```

- ENGINE_VERSION = `1.147.0` - source of truth `agents/daemon_slayer/__init__.py:18`.
- Patch = `16.12.1` - `data/daemon_slayer/current.txt:1`; matches `/health`.
- Champions = 172 (cross-checked: `data/daemon_slayer/16.11.1/champions.json` `data` map = 172 entries).
- Items = 706 in the loaded table (full table incl. Arena `22`-prefixed mirrors). **RM-203
  CORRECTION 2026-08-15:** the `547/547 covered` claim that stood here was never a ratio -
  547 was `len(ITEM_EFFECTS)` on 2026-05-06 written twice. Live, population-labelled item
  coverage is `docs/DAEMON_SLAYER.md:10`, guarded by `tests/test_docs_ds_item_coverage_drift.py`.
- DS server live PID 14744 LISTENING on 127.0.0.1:8893 (verified `netstat`).
- Tests on disk: 7317 `def test_` in `agents/daemon_slayer/tests/` (246 files) + 6807 in
  `tests/` (DS-pinning + route + live-integration). `docs/DAEMON_SLAYER.md:5` header says
  "7361 tests" / ENGINE 1.144.0 - that is the DS-dir figure and is NEAR-current (7317 now),
  not inflated; the ENGINE/patch line in that header IS stale (doc says 1.144.0, live is 1.147.0).

DOC-DRIFT FOUND (cosmetic, Tier-0, out of scope for this analysis but logged):
`docs/DAEMON_SLAYER.md:5` "ENGINE_VERSION 1.144.0 - 7361 tests" and line 139 "5931 tests" /
line 119 endpoint list lag the live 1.147.0 / 7317. ROADMAP/LEDGER are pointer-correct.

---

## 2. GENUINELY-OPEN GAPS

Each gap is real, additive, and NOT on the CLOSED list (section 3). EFFORT S/M/L,
RISK, and whether it needs a NEW extractor key / schema seam (most remaining DS growth
does - `reference_ds_forward_marker_exhausted`, the existing forward-marker accessor
queue is provably dry as of item 348).

### (a) Scorer-valuation residuals

- **a1. Static-cooldown ability-haste consumer (the 6th item-225 sidecar).** 5 of the 6
  sidecar buckets are wired (ammo/geometry/recharge/mode_modifiers/missile); the
  `static_cd` accessor is staged honest-no-consumer because the wiki static-CD value is
  unreliable and there is no haste model to feed it (`docs/ROADMAP_HISTORY.md` item
  225/234; `agents/daemon_slayer/data_loader.py`). WHY IT MATTERS: ability scorers fall
  back to `1/cooldown x mana_uptime` cast-rate when no rewind data exists, so a real
  haste-aware static-CD model would tighten the mage/burst cast frequency. EFFORT M.
  RISK med (a wrong CD model silently mis-ranks every caster). NEEDS NEW SCHEMA SEAM: yes
  (a name-bridge + ability-haste application model, not a forward-marker).

- **a2. Spear-of-Shojin / lethality / takedown / kit-axis valuation flips (DSV2/3/4,
  DSP2/8/11).** These scorer seams are SHIPPED + tested but DEFAULT-OFF and byte-identical
  until flipped (`docs/LIVE_GAME_GATED_SYNC.md` section B; engine 1.125.0-1.135.0). They
  are not a "missing capability" - the capability exists; what is lacking is the
  validated default-ON flip. Tracked in bucket (e). EFFORT S each (flip + restart).
  RISK low-med (each re-ranks a real build; "saner not different" eyeball required).
  No new seam.

- **a3. Tail of latent zero-output / degenerate scorer cases.** The cross-eval
  (`ops/audit/ds_cross_eval/`) found 3 systemic clusters; cluster C (Aphelios dps zero
  basic-attack) was fixed at ENGINE 1.128.0, but the doc notes Cassiopeia/Fiddlesticks/
  Sylas share the latent basic=0 shape and clusters A (archetype-vs-ARAM-win divergence)
  and B (generic-marksman-template on AD scorers) are flagged for a "gated Tier-2 next
  pass" (`project_ds_comprehensive_cross_eval` memory; `ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md`).
  WHY: these are valuation-quality residuals, not crashes. EFFORT M. RISK med. Cluster A/B
  may need per-champion curation, not a new key.

### (b) Data-source / extractor gaps

- **b1. The cdragon Phase-2 ratio hard-tail (~174 Meraki-fallback blocks).** Censused +
  DEFERRED (item 351): ~174 of 577 ratio blocks in `cdragon_ability_ratios.json` need live
  target/stack/branch state (the item-232 live-state class, permanently Meraki-fallback);
  292 are emission-guard aggregates that must stay fallback by design; 111 by-level blocks
  are drift-checked ALIGNED-not-stale. WHY: a fuller calc-graph resolver would let the
  mage scorer read exact per-rank ratios instead of a Meraki aggregate. EFFORT L. RISK
  high (a resolver is a fragile per-patch authoring surface). NEEDS NEW EXTRACTOR KEY: yes
  - explicitly do NOT re-pitch a resolver for this tail (memory CLOSED note, item 351) -
  the only remaining cdragon growth needs a brand-new key, so this is a "known frontier",
  not an action item.

- **b2. `wiki_ability_stats` magnitude markup (1046 abilities).** The one unmined
  DataSnapshot lane; every `*_raw` key is unparsed wiki markup (`{{fd|0.25}}`, `Varied`,
  `none`) and trait flags are noisy tri-state (`reference_ds_forward_marker_exhausted`).
  WHY: a fragile-parser job could surface new scalars (e.g. exact AA windup tails). EFFORT
  L. RISK high (markup drifts per patch). NEEDS NEW EXTRACTOR KEY: yes (an authoring job,
  not a forward-marker scout - the scout queue is proven dry).

- **b3. The 3 permanently-deferred items.** Lightning Braid (no Meraki formula + DPS-
  negative), Kinkou Jitte (directional weakpoint geometry unmodelable), Mejai's Arena
  mirror (no Arena DDragon id) - `docs/DAEMON_SLAYER.md:185-187`. WHY: completeness
  footnote. EFFORT N/A (genuinely unmodelable / no upstream data). These are "as complete
  as the data allows", listed for honesty.

### (c) Mode coverage (Arena / ARAM / URF specifics)

- **c1. Arena augment valuation into the ranker.** The augment OCR -> recommender path
  ships (`core/augment_recommender.py`; DS has `augments.py` + `augment_formula_eval.py`),
  but the Arena augment-select render is proven only by snapshot fixtures (no live Arena
  game has run; LCU was offline) - `docs/LIVE_GAME_GATED_SYNC.md` section D. The
  augment LCU/:2999 MID-GAME API is a confirmed dead-end (section 3); OCR is the proven
  path and is built. WHAT IS LACKING: a live Arena game to validate OCR->rank, plus the
  `set_augment_intent` 4-patch endpoint discovery. EFFORT S (validation) + S (probe).
  RISK low. No new engine seam.

- **c2. URF / One-for-All / Ultra-Spell-Book / Nexus-Blitz mode multipliers.** The
  `mode_modifiers` bucket wires URF/OFA/USB/NB dps/ehp mults + Arena base growth (item
  232, ENGINE 1.67.0) behind `apply_mode_modifiers` which is DEFAULT-OFF pending a live
  re-rank in those modes. WHY: RC's live pipeline is SR/ARAM/Arena-first; URF-family
  coverage exists in the engine but is unvalidated and unflipped. EFFORT S (flip) but
  gated on actually playing those rotating modes. RISK low. No new seam.

- **c3. F2 cost-ceiling for the ARAM/Arena 6000g mega-items.** SHIPPED DEFAULT-OFF
  (ENGINE 1.142.0) - Void Immolation (`223069`) floats to rank 1 by absolute-delta sort
  in every ARAM/Arena comp cell on hybrid/ehp scorers; the `cost_ceiling` gate is built
  but not flipped (`docs/LIVE_GAME_GATED_SYNC.md`). This is a ranking-surface artifact,
  not build-correctness. EFFORT S. RISK low (behavioral, not WIN-gated). No new seam.

### (d) Validation / outcome-anchoring (rewind WIN correlation)

- **d1. Cross-eval harness EXISTS and is complete; the FLIPS it recommends are not all
  landed.** `ops/audit/ds_cross_eval/` is a full 172-champion DS-pick-vs-actual-WIN
  correlation deliverable (PROGRAM/REPORT/TIER2_REPORT/SYSTEMIC_FINDINGS + per-champion
  JSON), anchored on `rewind_history.db` WIN outcomes (n=2941, ARAM n=2081); DONE
  2026-06-16 commit 89934b80, 172/172 (`project_ds_comprehensive_cross_eval` memory). So
  the validation SURFACE is not a gap. WHAT IS LACKING: the harness produced WIN-evidence
  for B1 (melee-gate), DSP11 (kit-axis), RF1 (bruiser-survivability) - those still need
  the operator's default-ON sign-off (bucket e); and clusters A/B are an open Tier-2
  re-tune (a3). EFFORT M (the re-tune). RISK med.

- **d2. Live calibration log not yet analyzed (50-game threshold).** `core/ds_calibration.py`
  appends DS picks per tick to `data/ds_calibration.jsonl`; the join-vs-rewind analysis
  fires only after 50+ games and is "accumulating" (`docs/DAEMON_SLAYER.md:191-193`). This
  is a passive accrual gate, not missing code. EFFORT S (run the analysis once the log
  fills). RISK low.

- **d3. HZ build-flip + laning-agreement gates are HOLD on corpus size.** The
  Haiku-to-ZERO build-order flip gate (`tools/replay_build_order_validate.py`) and the
  HZ laning-agreement read currently report flip_ready=False (95% CI crosses zero on ~651
  ARAM matches) - they need `rewind_history.db` to grow before they can flip
  (`docs/LIVE_GAME_GATED_SYNC.md` section C; `reference_hz_laning_agreement_gate`). EFFORT
  S (re-run when corpus grows). RISK low. Accrual gate, not new code.

### (e) Live-flip backlog (default-OFF seams awaiting validation)

This is the single largest concrete bucket and it is almost entirely VALIDATION, not
new engine code. Source: `docs/LIVE_GAME_GATED_SYNC.md` (the headless loop maintains it).

- **34 open gated boxes** across sections A-F at the 2026-06-17 bundle plan.
- **11 flag-ready re-rank seams DEFAULT-OFF, built + tested, awaiting a "saner not
  different" eyeball in a real game:** DSV2, DSV3, DSV4, DSP2, DSP8, DSP11 (dps+burst),
  RF1, RF2, RF3+RF6, B1 (apply_melee_aa_gate), F2 (cost_ceiling). The harness
  `ops/audit/ds_perm_swarm/live_flip_eyeball.py` dumps OFF-vs-ON top-6 per (champ, seam)
  so all 11 can be eyeballed in 3 games (SR+ARAM+Arena) without a per-seam :8893 restart.
  Of these, DSP11 (2026-06-17), RF1 (2026-06-18 Yasuo), and B1 (WIN-validated in
  TIER2_REPORT) are already FLIP-READY pending only the toggle.
- **Seams NOT yet wired (need a consumer/producer first, then a flip):** DSP4
  (`score_completion_runes` - a burst-NUMBER delta, needs a runes set at call), DSP5/6/7
  (summoner / enemy-rune / ally-grant CONSUMERS shipped at ENGINE 1.140.0 in
  `dsp_live_consumers.py` but still need the LIVE summoner/rune/ally sets PLUMBED into a
  call site + eyeball), and anti-tank P3.2 (`antitank.compute_antitank_live` PRODUCER
  shipped, but the /anti-tank route still calls the static `compute_antitank` - a
  survivability/draft surface must call the live variant).
- **Phase-D default-ON flips** (`apply_passive_damage`, the 4 non-every-AA `on_hit`,
  per-stack `assumed_stacks`) need the structured cadence + a live re-rank
  (`docs/ROADMAP_HISTORY.md` "DS Phase D").
- **Anivia P revive + Orianna E ally-resist** are DIFFERENT-SEAM exclusions, not the
  flat-add registry: revive shipped as the EHP-numerator multiplier (`apply_passive_revive`,
  ENGINE 1.101.0, `_passive_revive_overrides.py`) DEFAULT-OFF pending egg-survive feedback;
  Orianna E is a per-ally ball-attached grant in the item-277 ally-grant ecosystem
  (`dsp_live_consumers.ally_protected_ehp`) needing a live-input wire, not a flag flip.

EFFORT for the whole bucket: mostly S-per-item but BLOCKED on live games (planned
2026-06-17+). RISK low-med per flip. No new engine code for the 11 flag-ready seams.

### (f) Test / coverage / doc gaps

- **f1. `docs/DAEMON_SLAYER.md` header drift.** Lines 5 / 119 / 139 lag live (1.144.0 ->
  1.147.0; 5931/7361 -> 7317; endpoint list missing the newest scorer routes). Tier-0
  cosmetic; a DS-batch docs-sync job (coverage prose must be recomputed by the DS-batch
  procedure, never a flat count - `feedback_ds_coverage_prose_recompute`). EFFORT S.
- **f2. cdragon by-level vs Meraki spell-rank axis is documented as ALIGNED-not-stale**
  but there is no standing automated drift guard for that specific alignment beyond the
  one-off census (item 351). A reusable per-patch alignment check would close it. EFFORT
  S. RISK low.
- **f3. No single automated "engine truth vs docs" reconciler** - the header drift in f1
  recurs every ENGINE bump because nothing fails CI on it (CI runs no pytest; local dual-
  suite is the only gate - `feedback_ds_bump_run_tests_dir`). A size-budgeted doc-pin test
  would catch it. EFFORT S. RISK low.

---

## 3. CLOSED / DO-NOT-REOPEN

Considered and explicitly out of scope - operator-CLOSED or machine-guard-saturated.
Listed so they are not re-pitched as "gaps".

- **Conditional-target-state Part-2 (s232)** - permanently shelved; an s232 saturation
  guard exists. Do NOT re-pitch Part-2 or re-scan for conditional candidates.
- **block_index / form_index / max_priority / combo_sequence registries** - provably
  saturated by machine guard (s223-s232, 5-way scans returned 0 / only-noise). Further
  growth needs a schema lift, not an uncovered-champion scan.
- **The 6-scorer archetype plan** (carry/tank/bruiser/mage/assassin/enchanter) is FULLY
  wired through `rank_for_primary_archetype()` with no dispatcher fallbacks. Do NOT pitch
  a 7th scorer as "missing" - the 17+ SCORED AXES (incl. anti-tank, extended-duel,
  cc_blended_ehp, cc_conditional, sustain, mobility, threatrange, waveclear, zonecontrol,
  objdamage, scaling) are additive read-only surfaces, already shipped.
- **Augment LCU / :2999 MID-GAME API** - confirmed dead-end; no capture-free augment API
  mid-game. Augment-OCR is the proven path (and is built). Do NOT re-pitch an LCU augment API.
- **effects.py re-merge / `__all__` / FastMCP-or-SDK rewrite of the stdlib MCP servers** -
  CLOSED (AUTONOMOUS_AUDIT s5 exhausted; the facade split shipped s246).
- **ML win-predictors / CV-minimap / voice / `riot-offline-mode` / full `.rofl` packet
  parse** - all CLOSED (`CLAUDE.md` Settled). Not DS scope.
- **DS forward-marker accessor scout fanouts** - the un-taken `-> float|None` accessor
  queue is provably dry (item 348). Do NOT spawn another scout; the next magnitude lift
  needs a NEW extractor key (b1/b2), not another fanout.
- **`core/build_order.py` family map** - engine-authoritative no-double-unique rule; a
  guard test fails on any family literal. Do NOT add one.

---

## 4. DEFINITION OF DONE + HONEST VERDICT

"Truly complete besides patch updates" would mean ALL of:

- [ ] Every default-OFF scorer seam (the 11 flag-ready DSV/DSP/RF/B1/F2 family) flipped
      default-ON after a live "saner not different" re-rank, or explicitly left off with a
      recorded reason. (Today: 3 of 11 flip-ready, 0 flipped; blocked on live games.)
- [ ] Every NOT-yet-wired consumer/producer (DSP4/5/6/7, anti-tank P3.2 live) plumbed to a
      live call site and eyeballed. (Today: consumers/producers shipped, call-site wires open.)
- [ ] Anivia P revive + Orianna E ally-resist validated and flipped (their different seams
      are built). (Today: built, default-OFF, awaiting live feedback.)
- [ ] The 3 cross-eval systemic clusters (A archetype-vs-ARAM-win, B marksman-template on
      AD scorers, C Aphelios-family zero-output) all resolved; cluster C fixed (1.128.0),
      A+B still an open Tier-2 re-tune.
- [ ] The static-CD ability-haste consumer either built (new schema seam) or formally
      deferred-permanent like the other 3 unmodelable items.
- [ ] Live calibration (`ds_calibration.jsonl`) and HZ build-flip / laning-agreement gates
      reach their corpus thresholds and either flip or are re-deferred with evidence.
- [ ] `docs/DAEMON_SLAYER.md` engine/test/endpoint header reconciled to live (Tier-0), and
      a standing doc-pin guard prevents the recurring drift.
- [ ] (Forever-open by nature) Each new patch: re-extract, copy-forward the 3 hand-curated
      items, re-pin fixtures, bump ENGINE, restart :8893 - the SWARM patch-refresh workflow.

HONEST VERDICT: DS is approximately **90-93% of the way to "truly complete besides patch
updates"** on capability, and the remaining 7-10% is dominated by VALIDATION, not new
engine code. The math substrate, 6 archetype scorers, 17+ additive axes, complete shop-legal
item coverage (`docs/DAEMON_SLAYER.md:10`), per-spell CC ecosystem, and the WIN-correlation harness are all
SHIPPED and saturated. The 3-5 things standing between here and the line are:

1. **The live-flip backlog** (34 gated boxes; 11 flag-ready seams) - needs real games to
   eyeball, then a toggle + :8893 restart. This is the biggest single block and is pure
   validation.
2. **Wiring the 4-5 shipped-but-unconsumed live producers/consumers** (DSP4/5/6/7 +
   anti-tank P3.2 live) to actual call sites.
3. **The 2 cross-eval systemic clusters (A + B)** - a gated Tier-2 valuation re-tune that
   may need per-champion curation.
4. **The static-CD haste consumer** (a1) - the only "real new engine code" residual, and it
   needs a NEW schema seam (a name-bridge + haste model), so it is genuinely hard, not just
   un-done.
5. **The known-frontier data tails** (cdragon ratio hard-tail b1, wiki markup b2) - these
   need NEW extractor keys and are documented as "do not resolve with the current schema";
   they are the asymptotic last mile that a balance-patched game will never fully close.

So: never literally 100% (it is a live game), but the additive-work frontier is small,
enumerated, and mostly gated on the operator playing a few real games rather than on
writing more engine.
