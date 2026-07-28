# LEAP-07 - build-coherence calibration round 2 (three OQ24/OQ25 residuals, one session)

> P3 AMENDMENT - MANDATORY RETIER (judge panel 2026-07-17, 2/3 refute; supersedes
> every Tier-2/ENGINE-bump/Share/DS-restart instruction below):
> This slice touches ONLY core/-side client coherence policy - the production DS
> engine has ZERO core/ coherence consumers (probe-confirmed) and build_orders_*.json
> Family A tables carry NO engine_version field to re-stamp. Precedent: LEDGER 885
> (Step-1b) shipped a behavior-changing core coherence edit with NO bump; LEAP-04
> ghost list names the false-bump anti-pattern.
> EXECUTE AS: Tier-1-plus-regen - (a) NO ENGINE_VERSION bump, NO Share mirror, NO DS
> :8893 restart; (b) py_compile + core module tests + the build-coherence test files
> named below; (c) precompute regen via the LEAP-04 procedure (engine-less, full
> roster) AFTER core edits; (d) RC restart via restart_trigger.txt only (client-side
> policy loads in RC process); (e) DD1/DD2/DD3 scope, ACs, ghost list otherwise
> unchanged; ACs that assert an ENGINE bump are struck.
> SEQUENCING: run AFTER LEAP-04 (this spec consumes its regen procedure + guard).

Status: SPEC (author Fable 5, 2026-07-16). Execution: one Opus 4.8 session, max effort.
Program: Fable 5 Forward Leap portfolio (docs/specs/2026-07-16-fable5-forward-leap-kickoff.md).
Closes: BACKLOG.md:13 OQ24 residual tail (4) [Zeri AP-on-AD class] + docs/ORCHESTRATION_PLAN.md:362
  (OQ24-Step1b Kai'Sa Eclipse#6 light-dock) + docs/ORCHESTRATION_PLAN.md:360 (OQ25 NOW bucket:
  fight_length allow-map extension to Varus/MF).
Predecessor context: docs/specs/2026-07-13-ds-build-coherence-refactor.md (the coherence dock,
  Step-1a/1b = LEDGER 874/885), docs/_archive/2026-07-28-research-consolidation/OQ25_meta_divergence_report.md (OQ25 findings),
  LEAP-04-build-order-precompute-backfill.md (the shared regen chokepoint proof, sibling spec).

---

## GOAL

Front-load the thinking into specs; execution sessions are typing, not deciding.

Close the three cited build-coherence residuals that survived OQ24/OQ25 in ONE session, each
pre-decided to a concrete, sim-honest, RED-first-testable design:

1. Zeri Lich Bane / Liandry's AP-on-AD-marksman items need their OWN coherence class distinct
   from the crit/on-hit AD bucket (coherence.py:138-140 names it a deferred slice).
2. Kai'Sa Eclipse #6 light-dock calibration - the coherence dock under-penalized Eclipse for
   Kai'Sa vs the fully-clean Jhin/Varus/MF cases at Step-1b (engine 1.208.0).
3. fight_length allow-map extension - the per-champ burst lever shipped for Jhin extends to the
   two unmapped lethality/crit carries Varus + Miss Fortune.

Every decision below honors the standing constraint (memory project_ds_build_reco_optimal_not_
winrate): fix ONLY sim-incoherent artifacts, NEVER flip the kit axis, validate PER-CHAMPION.

---

## EVIDENCE (all probed live 2026-07-16; engine 1.216.0, patch 16.14.1, 173 champs / 706 items)

Live engine confirmed via `http://127.0.0.1:8893/health` (the DS server speaks PLAIN HTTP on
:8893, not HTTPS - curl `https://` returns HTTP 000 on Legion; use `http://` or urllib).

Item ids (from data/daemon_slayer/16.14.1/items.json; SR-purchasable unless noted):
  * Lich Bane 3100 (Arena mirror 223100) - tags SpellDamage/OnHit/NonbootsMovement/AbilityHaste;
    100 AP + 6% MS. NOT in any kit_synergy curated set today.
  * Liandry's Torment 6653 (Arena mirror 226653 "Liandry's Anguish") - Health/SpellDamage;
    300 HP + 60 AP. Already in kit_synergy._MAXHP_DAMAGE_IDS ("%maxHP burn").
  * Eclipse 6692 (Arena mirror 226692) - Damage/CDR/AbilityHaste; 60 AD. In
    kit_synergy._BONUS_AD_SCALING_IDS. Bonus-AD/lethality = off-axis for an on-hit marksman.
  * Essence Reaver 3508 - the Step-1a/1b artifact; in _BONUS_AD_SCALING_IDS AND _SPELLBLADE_IDS.
  * Dusk and Dawn 2510 - NEW 16.14 item; Health/AttackSpeed/SpellDamage/OnHit/AbilityHaste;
    300 HP + 60 AP + 20% AS + OnHit. A LEGIT on-hit hybrid (do NOT dock - see GHOST LIST).
  * Cruelty 667109 - Armor/SpellDamage/MagicResist; 25 armor + 60 AP + 25 MR. A DEFENSIVE item;
    the R119 Meraki-absent data phantom (LEDGER 903 / ORCHESTRATION_PLAN.md:354). Out of scope.

Coherence dock (core/build_planner/coherence.py, the carry chokepoint):
  * `coherence_rerank(rows, champion, top, fight_length)` :116 - early-returns `rows[:top]`
    byte-identical for a non-carry archetype OR `is_caster_marksman` (:159). Otherwise sorts by
    `_coherence_adj` = base - mu*pen + w*fit.
  * Two tuning pairs: delta branch (`fight_length` None/<=0) uses `_MU=10.0`, `_W=6.0` (:49-50);
    engaged branch (positive `fight_length`) uses `_MU_EFF=80.0`, `_W_EFF=6.0` (:69-70) over the
    burst-inclusive `effective_score` base. `_CARRY_ARCHETYPE="carry"` (:75).
  * `fit = stat_fit(iid, champ)`, `pen = anti_synergy_penalty(iid, champ)` from
    core/build_planner/kit_synergy.py. `_SPELLBLADE_NONUSER_PENALTY=2.0` (:166) docks a
    Sheen-line proc on a non-spellblade-user.

Membership gate (core/build_planner/champ_kit_data.py):
  * `is_caster_marksman(champ)` :162 - Marksman AND Mage tag AND `_ability_agg("ap") >= 2.0`
    (`_CASTER_MKS_ABIL_AP_FLOOR`, :159). This is the exact sibling pattern the new AP-hybrid
    class clones. Zeri ap_agg = 1.95 (measured), Kai'Sa 1.40, Jhin 1.60, Varus 1.25, MF 1.20.

fight_length allow-map (core/ds_champion_fight_length.py):
  * `_CHAMPION_FIGHT_LENGTH` :105 = {jhin:0.5, draven:0.3, samira:0.3, twitch:0.5, caitlyn:0.5,
    jinx:0.5}. Leaf module, ZERO engine imports (split-brain-safe). Docstring:74-88 pins the
    validated [0.3, 0.75] flat-lift band and the "retains a sustained component -> 0.5,
    pure-burst -> 0.3" tier rule. Varus + MF are ABSENT (resolve to None -> byte-identical).

Generator -> coherence propagation (resolves the OQ24 OPEN design Q; per LEAP-04 evidence):
  * tools/daemon_slayer_build_orders_generate.py:88 imports `core.daemon_slayer_client`; the
    generator computes each build via `core.build_order.plan_build_order`, which defaults its
    ranker to `daemon_slayer_client.rank_for_primary_archetype`, and that applies
    `coherence_rerank(..., fight_length=_carry_fight_length)` CLIENT-SIDE (LEAP-04 EVIDENCE
    :36-54, self-witnessed at daemon_slayer_client.py:1523/1585). CONSEQUENCE: the coherence
    dock AND the fight_length allow-map propagate into the precomputed build_orders after a
    regen. The precompute fix for residuals 1/3 IS reachable - regen picks it up.

Live per-champion rankings (raw POST /rank, level 13; the server default fight_length=None so
the delta branch governs the dock):

  Kai'Sa, armor 30: Runaan's, Kraken, Stormrazor, Essence Reaver, Guinsoo, IE, Yun Tal,
    Terminus, Voltaic, Statikk. Eclipse ABSENT from top-10.
  Kai'Sa, armor 100: Stormrazor, Runaan's, Kraken, Guinsoo, Dusk and Dawn, Terminus, Wit's End,
    Essence Reaver, Statikk, IE. Eclipse ABSENT from top-10.
  Kai'Sa precompute (build_orders_sr.json, generated 2026-07-16, all 3 comp-classes): BORK,
    Berserker's, Runaan's, Terminus, Kraken, Lord Dominik's. Eclipse ABSENT; #6 = LDR.

  => The Kai'Sa Eclipse#6 residual (observed at engine 1.208.0 via ds-preview SR L13, OP:362)
     is STALE at 1.216.0: eight engine bumps later Eclipse no longer surfaces for Kai'Sa in
     the raw ranking OR the precompute. This reframes residual 2 as a REGRESSION PIN, not a
     new dock (see DESIGN DECISIONS 2).

  Zeri fit/pen (delta branch, live): BORK 3153 fit 2.414 / pen 0.0 (her real core); Lich Bane
    3100 fit 1.267 / pen 0.0; Eclipse 6692 fit 1.284 / pen 0.0; Essence Reaver 3508 fit 1.053 /
    pen 2.0 (docked, correct); Liandry's 6653 fit 0.390 / pen 0.0. Zeri tags=['Marksman'] (NO
    Mage tag), archetype=carry, is_caster_marksman=False, spellblade_user=False - she takes the
    STANDARD carry dock today.

  Engine-AP-credit control (Lich Bane delta, armor 100, L13): Zeri 32.8, Caitlyn 39.2, Jinx
    37.0. Zeri's Lich Bane delta is LOWER than the two pure-AD controls - the DS engine does
    NOT credit Zeri's Q ability-AP for Lich Bane above a pure-AD marksman baseline; the delta is
    the on-hit / spellblade-style proc the engine models per-attack for ANY marksman. Liandry's
    delta = out-of-top-40 for all three. Eclipse delta: Zeri 7.0, Caitlyn 16.5, Jinx 10.8 (all
    buried). This is the decisive sim evidence for DESIGN DECISION 1.

  Zeri precompute (build_orders_sr.json): BORK, Berserker's, Dusk and Dawn, Liandry's Torment,
    Cruelty, Terminus. The two questionable rows: Liandry's #4 (surfaces via the greedy
    sequential build-order path, NOT the single-shot raw /rank where it is out-of-top-40) and
    Cruelty #5 (the 667109 phantom, out of scope). Its flat delta 43.4 at BOTH armor 30 and 100
    confirms Cruelty is not armor-modeled = a data artifact, not a coherence artifact.

---

## SCOPE

- Residual 1: DEFINE an AP-on-AD-marksman coherence class (predicate + allow-map + item set +
  membership rule) in champ_kit_data.py, wired into coherence.py, sibling to is_caster_marksman.
- Residual 2: a Kai'Sa Eclipse regression PIN (primary) plus a bounded dock-calibration
  CONTINGENCY if the exact ds-preview target still surfaces Eclipse in Kai'Sa's top-6.
- Residual 3: extend `_CHAMPION_FIGHT_LENGTH` with varus + missfortune, each at a pre-decided,
  band-validated value, cloning the Jhin entry shape.
- One precompute regen (per LEAP-04 procedure) so the static build_orders reflect residual 3
  (and residual 1 if it lands a behavior change), + Share mirror + DS restart.

## NON-SCOPE (explicitly out; do NOT expand the slice)

- Cruelty 667109 the Meraki-absent data phantom (R119 / LEDGER 903, DATA-layer, BACKLOG). Its
  presence in Zeri's precompute is a separate fix; do not fold it here.
- Dusk and Dawn 2510 - a legit on-hit hybrid (OnHit + AS + AP), coherent for on-hit marksmen; do
  NOT dock it (GHOST LIST).
- L5 fed-conditional / dynamic fight_length (needs live snowball-state plumbing) - a separate
  ds-engine cycle. L6 Stormrazor 3097 dock - REFUTED-CLOSED (LEDGER 888; GHOST LIST).
- The full build_order backfill MECHANISM + staleness guard - owned by LEAP-04; this spec only
  triggers the regen and consumes its procedure.
- Any kit-axis flip, any win-rate/meta-representation weighting, any change to the on-hit/crit
  marksman cluster beyond these three residuals (LEDGER 886 do-not-fix).

---

## DESIGN DECISIONS (pre-answered)

### DD1 - Zeri AP-on-AD-marksman distinct coherence class

New coherence class DEFINITION (champ_kit_data.py, sibling to is_caster_marksman):

```
_AP_HYBRID_ITEM_IDS = frozenset({"3100", "223100", "6653", "226653"})  # Lich Bane, Liandry's + Arena mirrors
_AP_HYBRID_MARKSMAN = frozenset()  # per-champion allow-map; EMPTY at ship (see membership rule)

def is_ap_hybrid_marksman(champ) -> bool:
    """A carry-archetype Marksman whose kit genuinely converts AP into sim DPS through an
    ability that the DS engine credits (so Lich Bane / Liandry's are ON-AXIS, not wasted stat).
    Explicit per-champion allow-map, mirroring _CHAMPION_FIGHT_LENGTH and is_caster_marksman -
    a champion earns membership ONLY when the RED test proves the engine credits its ability-AP
    for _AP_HYBRID_ITEM_IDS above a pure-AD-marksman baseline. Fail-soft False when unresolved."""
    return _norm(champ) in _AP_HYBRID_MARKSMAN
```

MEMBERSHIP RULE (the pre-answered decision, sim-honest): a marksman joins `_AP_HYBRID_MARKSMAN`
ONLY IF, in-process at the live engine, its `_AP_HYBRID_ITEM_IDS` deltas materially exceed a
pure-AD-marksman control (Caitlyn/Jinx) at a fixed target. At engine 1.216.0 Zeri does NOT clear
this bar (Lich Bane delta 32.8 < Caitlyn 39.2 / Jinx 37.0; Liandry's out-of-top-40 for all
three). THEREFORE the allow-map ships EMPTY and Zeri stays in the standard carry bucket -
byte-identical behavior. This is the R77/Stormrazor precedent (premise-refuted at ground truth
-> build the seam + the guard, ship NO behavior flip).

CLASS BEHAVIOR (wired in coherence.py, ready the moment a member qualifies):
  * MEMBER champ: `_AP_HYBRID_ITEM_IDS` are treated ON-AXIS - exempt from any AP-waste dock;
    scored on the member's kit weights, NOT the generic marksman AP-discount (mag*0.3).
  * NON-MEMBER carry marksman (Zeri + all pure-AD marksmen today): `_AP_HYBRID_ITEM_IDS` stay
    OFF-AXIS = eligible for the existing wasted-stat dock. NO NEW dock term is added unless the
    RED test proves a member-less marksman surfaces one of these items as a top-6 artifact in
    the GREEDY build-order path (Zeri's Liandry's #4). If reproduced AND not attributable to the
    Cruelty phantom adjacency, add a LIGHT off-axis AP-waste term (in-family with
    `_SPELLBLADE_NONUSER_PENALTY`, tuned to sink Liandry's below Zeri's on-hit core by a MEASURED
    effective_score margin, delta branch `_MU`). Default expectation from EVIDENCE: the greedy
    Liandry's is a Cruelty-adjacency effect, so the seam ships with NO dock and the Cruelty
    data-fix (separate) resolves the pollution. The RED test decides.

Net: DD1 delivers the class definition + membership rule the residual asked for, decides
(from ground truth) that no member qualifies today, and leaves behavior byte-identical unless
the greedy-path RED probe proves a genuine artifact. No kit-axis flip; no win-rate lift.

### DD2 - Kai'Sa Eclipse #6 light-dock calibration

PRIMARY (from EVIDENCE): the residual is STALE at 1.216.0 - Eclipse is absent from Kai'Sa's raw
top-10 (armor 30 and 100) AND her precompute. Deliverable = a REGRESSION PIN: assert Eclipse
(6692) stays OUT of Kai'Sa's coherence-reranked top-6, and assert the margin (Eclipse's
`_coherence_adj` sits below Kai'Sa's on-hit #6 by a measured delta). This locks the
already-clean state so a future engine drift cannot silently resurface it.

RED-FIRST reproduction gate (mandatory before any dock change): reproduce the Step-1b scenario
at the EXACT ds-preview SR L13 target (the live liveclient-derived armor/MR/HP curve, NOT the
flat armor 30/100 approximation this spec probed). My flat probes + the precompute both show
Eclipse gone, but the precise ds-preview target was not re-probed here (UNVERIFIED-SKIP 1).

CONTINGENCY (only if the exact target still surfaces Eclipse in Kai'Sa's top-6): calibrate the
dock. Root cause of the historical under-penalty: Eclipse 6692 carries `anti_synergy_penalty`
0.0 for on-hit marksmen (measured on Zeri: fit 1.284 / pen 0.0) because it is scored as a
bonus-AD MATCH item (in `_BONUS_AD_SCALING_IDS`) whose bonus-AD weight is low (0.3) but not
NEGATIVE for an on-hit kit. Fix = give the Eclipse-class (pure bonus-AD/lethality, NO on-hit /
AS / crit) a small off-axis penalty for on-hit-dominant marksmen (on-hit weight >= 0.6), sized
in `_MU` units to drop Eclipse just below the on-hit #6, MATCHING the already-clean Jhin/Varus/
MF. Constrain to the on-hit marksman sub-case; the RED test must confirm no unrelated champ
flips (per-champion validation, not a generic ADC shape).

### DD3 - fight_length allow-map extension (Varus, Miss Fortune)

Add two entries to `_CHAMPION_FIGHT_LENGTH`, cloning the `"jhin": 0.5,` shape + a docstring block:

```
    "varus": 0.5,
    "missfortune": 0.5,
```

VALUES + RATIONALE (both inside the docstring-pinned [0.3, 0.75] flat-lift band, "retains a
sustained component" tier = 0.5):
  * Miss Fortune 0.5 - crit-burst carry (Double Up + Bullet Time ult burst) that RETAINS a real
    sustained auto component (Strut MS + auto weaving), so 0.5 (the Caitlyn/Jinx/Jhin value)
    lifts her crit core (IE / The Collector / crit) with a gentler tilt than 0.3 off her
    sustained value. ap_agg 1.20, caster_mks False -> she takes the dock, so the effective_score
    branch (`_MU_EFF`) applies exactly as it does for the five L3 crit ADCs.
  * Varus 0.5 - lethality-poke identity (Q-charge + Chain-of-Corruption ult burst; real core
    Youmuu's / Serylda's / The Collector / lethality) BUT retains a genuine sustained on-hit
    build (Blighted Quiver). 0.5, not 0.3: the poke build is burst but the on-hit build is
    sustained, so the gentler "retains sustained" value is the conservative choice within the
    flat band. ap_agg 1.25, caster_mks False -> dock applies, effective_score branch.

Both are already in the carry bucket and already docked (caster_mks False), so this is a pure
allow-map addition; no coherence.py change is needed for DD3. The value-lift claim (0.5 surfaces
each champ's burst core in-process) is deferred to the RED test (UNVERIFIED-SKIP 2).

---

## TESTABLE ACCEPTANCE CRITERIA (RED-first, per-champion; assert computed deltas, not fragile orderings)

Write every test RED (failing) FIRST, then implement. Assert COMPUTED `effective_score` /
`_coherence_adj` / fit / pen deltas and margins, never a raw index that a one-item shuffle breaks.

DD1 (tests/test_champ_kit_data.py + tests/test_carry_coherence_rerank.py):
  * `is_ap_hybrid_marksman` exists; returns False for Zeri, Caitlyn, Jinx, Kai'Sa at ship
    (allow-map empty). `_AP_HYBRID_ITEM_IDS == {3100,223100,6653,226653}`.
  * MEMBERSHIP-GATE guard (non-vacuous): a probe test asserts Zeri's live Lich Bane delta does
    NOT exceed the pure-AD control (Caitlyn) by the membership threshold -> documents WHY Zeri
    is excluded at 1.216.0. If a member is ever added, the same gate must pass for it.
  * BEHAVIOR: with the allow-map empty, `coherence_rerank` output for Zeri is byte-identical to
    the pre-LEAP-07 baseline (regression pin on the full top-6 id list).
  * GREEDY-PATH probe (decides the contingency): assert whether Zeri's greedy build-order
    surfaces Liandry's 6653 in the top-6 with Cruelty 667109 EXCLUDED from the pool. If it
    still does -> the light off-axis dock lands and the test asserts Liandry's `_coherence_adj`
    falls below Zeri's on-hit #6 by a measured margin. If it does not -> no dock; pin the
    byte-identical build.

DD2 (tests/test_carry_coherence_rerank.py):
  * Kai'Sa REGRESSION PIN: Eclipse 6692 is NOT in `coherence_rerank`'s Kai'Sa top-6, and
    Eclipse's `_coherence_adj` < the #6 row's `_coherence_adj` by a measured margin, at the SR
    L13 ds-preview target. CONTROL: the same assertion holds for Jhin, Varus, MF (the
    fully-clean cases) - the pin proves Kai'Sa now MATCHES them.
  * If the reproduction gate surfaces Eclipse (contingency active): a RED test that Eclipse IS
    in the top-6 pre-fix and OUT post-fix, plus a no-collateral assertion (a control on-hit
    marksman that legitimately wanted a bonus-AD item is unaffected).

DD3 (tests/test_l3_crit_adc_fight_length.py or a sibling tests/test_varus_mf_fight_length.py):
  * `champion_fight_length("Varus") == 0.5` and `champion_fight_length("Miss Fortune") == 0.5`;
    both in [0.3, 0.75]. Unmapped control (e.g. Ashe, Aphelios) still returns None.
  * LIFT proof (in-process via rank_for_primary_archetype at the tanky mode-curve target): with
    fight_length engaged, Varus's lethality core (Youmuu's/Serylda's/Collector/IE) ranks above
    the sustained on-hit stat-stick (BORK/Runaan's demoted), and MF's IE/Collector core lifts;
    assert the effective_score of the burst core exceeds the sustained item by a measured delta.
  * REGRESSION: a champion NOT added stays byte-identical (no burst term paid).

FULL-SUITE GATE: the DS-dir suite (agents/daemon_slayer/tests) + the RC suite (tests/) both
green; zero net regression attributable to this slice (isolate any pre-existing flakes per the
LEDGER-828 coach_poll_offload / roadmap-budget precedent).

---

## R5 TIER = Tier-2

Directed tier: Tier-2 - ENGINE bump, dual suite (DS-dir + tests/), Share mirror, DS :8893
restart, precompute re-stamp.

Load-bearing trigger: DD3 changes Varus + MF's STATIC precomputed build_orders (their carry
builds tilt toward the burst core once fight_length engages via the shared client chokepoint),
so the precompute MUST be regenerated + re-stamped + Share-mirrored. That regen + Share sync IS
the Tier-2 tax; the ENGINE_VERSION bump (1.216.0 -> 1.217.0, quoted-literal only per
feedback_engine_bump_quoted_literal_only) is the invalidation stamp for the patch-keyed static
tables + the DS restart signal.

NOTE for the execution session (state the assumption explicitly): the Step-1b precedent (LEDGER
885) shipped the sibling core-side coherence change WITHOUT an ENGINE bump, because core/ has
zero agents/daemon_slayer consumers (it is client-side policy, not engine math). If DD1 lands as
the expected empty-allow-map seam (no behavior change) and DD2 lands as a pure regression pin,
those two are independently Tier-1 (RC reload only). The ENGINE bump + Share + DS restart become
mandatory the moment the precompute is regenerated for DD3. Do the FULL Tier-2 ritual for the
batch since DD3 forces the regen. Regenerate per LEAP-04's procedure (the generator reaches the
coherence dock + fight_length allow-map through core.daemon_slayer_client, EVIDENCE above).

---

## FILES TOUCHED

Production:
  * core/ds_champion_fight_length.py - DD3: add "varus": 0.5, "missfortune": 0.5 to
    `_CHAMPION_FIGHT_LENGTH` + a docstring block (clone the Jhin/L3 rationale shape).
  * core/build_planner/champ_kit_data.py - DD1: `_AP_HYBRID_ITEM_IDS`, `_AP_HYBRID_MARKSMAN`
    (empty), `is_ap_hybrid_marksman()`.
  * core/build_planner/coherence.py - DD1: wire `is_ap_hybrid_marksman` into the class handling
    (on-axis exemption for members / off-axis eligibility for non-members). DD2 CONTINGENCY
    ONLY: the Eclipse-class on-hit-marksman dock hook.
  * core/build_planner/kit_synergy.py - DD1/DD2 CONTINGENCY ONLY: a light off-axis AP-waste term
    for `_AP_HYBRID_ITEM_IDS` on non-members and/or the Eclipse-class on-hit penalty. Untouched
    if the RED probes show no artifact (the expected DD1 outcome).

Tests (RED-first):
  * tests/test_champ_kit_data.py, tests/test_carry_coherence_rerank.py (DD1 + DD2),
    tests/test_l3_crit_adc_fight_length.py or tests/test_varus_mf_fight_length.py (DD3).

Regenerated / re-stamped (per LEAP-04 procedure):
  * data/daemon_slayer/16.14.1/build_orders_{sr,aram,arena}.json (+ any variant tables),
    Share/src/data/daemon_slayer/16.14.1/build_orders_*.json (Share mirror), the ENGINE_VERSION
    literal (agents/daemon_slayer bump to 1.217.0), CHANGELOG / anchor stamps as the regen
    tooling dictates.

---

## EST SESSIONS: 1   |   MODEL: claude-opus-4-8, effort max

The three residuals share the single carry-coherence chokepoint + one regen; one focused Opus
4.8 session is sufficient. DD1 is expected to be a define-the-seam / no-flip outcome, DD2 a
regression pin, DD3 a two-line allow-map addition - the weight is in the RED-first probes and
the Tier-2 regen, not in new logic.

---

## DONE RITUAL

1. All RED tests green; DS-dir + RC dual suite green; report exact pass/fail counts observed
   THIS run (re-run fresh, never carry a prior/subagent count forward).
2. Regenerate the precompute (LEAP-04 procedure), Share-mirror, `ds_share_sync --check` GREEN.
3. ENGINE 1.216.0 -> 1.217.0 (quoted-literal pins only); bounce DS :8893 (taskkill /F the held
   PID, confirm port free, schtasks /Run RC-DaemonSlayer, verify /health reports 1.217.0).
4. Live-verify: Kai'Sa still Eclipse-free, Varus/MF precompute tilts to their burst core, Zeri
   byte-identical (or the docked-Liandry's build if the contingency fired).
5. Commit (precommit truth-gate: ASCII-only, no banned glyphs, no net-new ruff), push, append
   the per-item entry to docs/LEDGER.md (NOT CLAUDE.md), sync ROADMAP/ORCHESTRATION_PLAN/BACKLOG
   (flip the three residual cells to DONE with the shipped sha), confirm CI green.

---

## GHOST LIST (do NOT do these; each is a settled negative)

- Stormrazor 3097 dock - REFUTED-CLOSED (LEDGER 888): Aphelios/Zeri Stormrazor is a coherent
  Energized on-hit/crit-AS core. Do NOT penalize it or reopen the L6 tail.
- Kit-axis flip - FORBIDDEN (memory project_ds_build_reco_optimal_not_winrate): fix ONLY
  sim-incoherent artifacts, optimal not win-rate. Zeri/Kai'Sa/Varus/MF stay carry/marksman.
- DSP11 gate - DO-NOT-REVERT: the Pyke/Corki kit-axis seam is load-bearing; this slice does not
  touch it.
- On-hit/crit marksman cluster (Ashe/Kai'Sa/Kog'Maw/Vayne/Kalista/Aphelios/Jinx/Caitlyn/Draven/
  Samira) - LEDGER 886 VALIDATED-CORRECT do-NOT-fix EXCEPT the three residuals scoped here.
- Cruelty 667109 - the R119 Meraki-absent data phantom (LEDGER 903). Its Zeri-precompute
  pollution is a DATA-layer fix (BACKLOG), NOT this coherence slice. Do not dock it as a
  coherence artifact and do not fold its data-fix in here.
- Dusk and Dawn 2510 - a legit NEW on-hit hybrid (OnHit + AS + AP + HP), coherent for on-hit
  marksmen. Do NOT dock it or mistake it for an Eclipse-class artifact.
- L5 fed-conditional / dynamic fight_length - a separate ds-engine cycle (needs live
  snowball-state); NON-SCOPE here.
- Generic ADC-shape validation - validate PER-CHAMPION (Zeri, Kai'Sa, Varus, MF each on their
  own kit); a single ADC-crit fixture is insufficient (Engine/Build Conventions).
- em-dashes / en-dashes / smart quotes - BANNED. 7-bit ASCII only; " - " for a clause break.
