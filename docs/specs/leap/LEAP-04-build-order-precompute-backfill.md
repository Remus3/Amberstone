# LEAP-04 - build_order precompute backfill (resolve the coherence-dock design Q, then spec the regen)

Status: SPEC (author Fable 5, 2026-07-16). Execution: one Opus 4.8 session, max effort.
Program: Fable 5 Forward Leap portfolio (docs/specs/2026-07-16-fable5-forward-leap-kickoff.md).
Closes: BACKLOG.md:13 OQ24 residual tail (2) + docs/ORCHESTRATION_PLAN.md:358 (OQ24-cycle11)
open design question. Predecessor context: docs/specs/2026-07-13-ds-build-coherence-refactor.md
(the coherence dock, Step-1a/1b, LEDGER 874/885).

---

## GOAL

Resolve, from code evidence, the OPEN DESIGN QUESTION that has blocked the build_order
precompute backfill since Step-1a: does the generator
`tools/daemon_slayer_build_orders_generate.py` bypass the core coherence dock (i.e. POST raw
to :8893)? Then spec the backfill so a cold execution session runs it and proves parity with
the live dock, and lands the missing staleness guard so this question never re-blocks a cycle.

Program north star (verbatim): "front-load the thinking into specs; execution sessions are
typing, not deciding".

---

## EVIDENCE (cited file:line, probed 2026-07-16)

Call chain, all IN-PROCESS in the RC / generator Python process:

1. `tools/daemon_slayer_build_orders_generate.py:89` imports `plan_build_order` from
   `core.build_order`; `:191` calls it per (champion, archetype, mode, comp-class) with
   `rank_kwargs={"enemy_ad_share":..., "enemy_ap_share":...}` and NO `rank_fn`, NO
   `fight_length`. `:303` calls `dsc.is_engine_up()` only as a LIVENESS GATE (refuses to
   write against a dead :8893), NOT as the ranking path.
2. `core/build_order.py:460 plan_build_order` - when `rank_fn is None` (the generator's case)
   it imports and uses `core.daemon_slayer_client.rank_for_primary_archetype` as the default
   ranker (`:506-511`).
3. `core/daemon_slayer_client.py:1141 rank_for_primary_archetype`:
   - `:1552` calls `rank_for(...)`, the thin HTTP client (module docstring `:1` "Thin HTTP
     client for the local Daemon Slayer engine on :8893"; `urlopen` at `:84`/`:98`). This
     POSTs the scoring request to :8893 and parses each row via `RankedItem.from_dict`.
   - `RankedItem.from_dict` (`:61-72`) parses `effective_score` (`:71`) - the field whose
     drop (pre-L4) made the dock's fight_length branch read a missing attr -> base 0.0 ->
     inert (docstring `:50-58`; shipped LEDGER 875 / OQ23).
   - `:1585` applies `coherence_rerank(rows, champion, top, fight_length=_carry_fight_length)`
     CLIENT-SIDE on those parsed rows, then returns the ranked dict.
4. `core/build_planner/coherence.py:116 coherence_rerank` - the dock. Early-returns
   `rows[:top]` byte-identical for a non-carry archetype OR a genuine caster-marksman
   (`:155-160`, gated by `is_caster_marksman` in `core/build_planner/champ_kit_data.py`, the
   Step-1b tightening). Otherwise docks the ER (3508) / Eclipse (6692) artifacts via
   `- mu*pen + w*fit` on both the delta_dps base and the fight_length-engaged
   effective_score base (`_coherence_adj`, `:78-113`).

Self-witnessing code comment (decisive): `core/daemon_slayer_client.py:1523` - the
squishy-burst-target swap "Covers both the live coach path and the offline build-order
backfill (shared chokepoint)." The engine source itself names the backfill as sharing this
client-side chokepoint.

DATA corroboration (probed the committed live table):
- `data/daemon_slayer/current.txt` = `16.14.1`.
- `data/daemon_slayer/16.14.1/build_orders_sr.json` `generated_at` = `2026-07-16T14:09:07Z`,
  `version` = `16.14.1`, committed `21db5626` (2026-07-16 patch refresh 16.13.1 -> 16.14.1).
  This regen ran AFTER Step-1a/1b (2026-07-13).
- Every Step-1b flipped crit-ADC cell in that committed table carries ZERO ER (3508) / Eclipse
  (6692) across all three comp-classes: Miss Fortune / Jhin / Kai'Sa / Varus / Twitch / Jinx /
  Caitlyn all artifacts=NONE. Pre-dock these champs surfaced the artifacts
  (docs/ORCHESTRATION_PLAN.md:362: MissFortune Eclipse#4 ER#6, Jhin ER#2, Kai'Sa ER#5
  Eclipse#6, Varus ER#4 Eclipse#6). Their absence is strongly consistent with the dock having
  been applied at the last regen.

Stamp / roster facts:
- Family A payload keys (generator `:240-245`, JSON confirmed, `tests/test_build_orders_generate.py:46-48`):
  `build_orders` (nested `{champ: {ad_heavy|balanced|ap_heavy: [item_id,...]}}`),
  `generated_at`, `mode`, `version` (= patch). NO `engine_version` stamp.
- Generator loads the FULL DDragon roster by default (`:152-164`); `--champion` narrows,
  `--mode all` (default) does sr+aram+arena. There is NO 10-champ seed footgun here (that is
  the OTHER tool, `core.build_order_precompute`, per R78 - see NON-SCOPE).
- Existing generator test `tests/test_build_orders_generate.py` monkeypatches
  `plan_build_order` to a deterministic fake (server-free) and pins schema / class mapping /
  atomic write / dry-run. It does NOT test dock parity or staleness.

UNVERIFIED-SKIP count: 0. Every claim above was probed to source.

---

## DESIGN ANSWER (definitive)

The generator does NOT bypass the core coherence dock. The OPEN Q premise ("does it POST raw
to :8893, bypassing the dock?") is FALSE as stated, resolved two independent ways:

- By CODE: the generator ranks through `plan_build_order` -> `rank_for_primary_archetype` ->
  `coherence_rerank`. The :8893 POST (inside `rank_for`) supplies only the RAW per-item scores
  (delta_dps, effective_score, burst_gain). The dock (artifact demotion + `is_caster_marksman`
  early-return + ranged off-class gate) runs CLIENT-SIDE, in-process, AFTER the POST, inside
  `rank_for_primary_archetype`. The generator inherits it because it uses the default
  `rank_fn` = the client wrapper that hosts the dock. It never calls raw `rank_for` and never
  POSTs to :8893 itself. Bypass would require the generator to do one of those; it does
  neither.
- By DATA: the committed 16.14.1 tables already show the dock's effect (zero ER/Eclipse on the
  seven Step-1b flipped crit-ADCs), because the 2026-07-16 patch refresh regenerated Family A
  through the same dock-enabled chokepoint.

Corollary - the Step-1a/1b change flows in for free. `is_caster_marksman`
(`core/build_planner/champ_kit_data.py`) gates `coherence_rerank`'s early-return, so tightening
it (Step-1b) automatically changes the generator's output for the flipped champs. There is no
"engine variant" or "re-route" to build - that whole branch of the OPEN Q is moot.

Required fix to the generator's ranking path: NONE. The generator already routes correctly.

The ONE hard dependency to VERIFY (not fix): `RankedItem.from_dict` must keep parsing
`effective_score` (`core/daemon_slayer_client.py:71`). It does today (LEDGER 875). If a future
change drops it, the dock's fight_length-engaged branch silently reverts to a target-blind
kit-fit sort for exactly the mapped crit-ADCs the dock targets (Jhin, Twitch, Caitlyn, Jinx,
Draven, Samira) - a no-op that would NOT crash and would NOT show a stamp diff. The acceptance
criteria PIN this so the regression is loud.

Net consequence for the backfill: the corrective regen appears ALREADY satisfied at 16.14.1
(the patch refresh did it). So LEAP-04's enduring deliverable is (a) run a confirmatory regen
and prove byte-parity-or-explained-diff, and (b) land the FIRST staleness guard for Family A
(it has none today - no engine_version stamp, no content-freshness test, unlike Family B), so
the next dock change or patch refresh that forgets Family A is caught in CI, not discovered a
cycle later. If the confirmatory regen surprises with a real diff, that diff IS the owed
backfill and gets committed.

---

## SCOPE

1. Run `python tools/daemon_slayer_build_orders_generate.py --mode all` (full roster, all 3
   modes) with DS :8893 UP and settled at the intended ENGINE_VERSION. Diff the output against
   the committed `data/daemon_slayer/16.14.1/build_orders_{sr,aram,arena}.json`.
   - Byte-identical (expected): commit nothing for the data; the regen is a freshness PROOF
     (the R87 stamp-only precedent). `generated_at` will differ - either revert the timestamp
     churn or accept the 3 timestamp-only lines; do not treat a pure `generated_at` delta as a
     content backfill.
   - Real content diff (validate before trusting): inspect the changed champs, confirm the
     change is a legitimate dock / engine effect (not a seed-clobber or a dead-engine empty
     table), then commit the regenerated tables as the owed backfill.
2. Add the FIRST Family A staleness + dock-parity guard (new test module). Two layers, mirroring
   the proven `tests/test_build_order_content_freshness.py` pattern:
   - Layer 1 (fast, per-commit, server-free): static read of the committed 16.14.1 tables.
     Stamp assertions (`version` == `current.txt`, `mode` == filename mode, `generated_at`
     ISO-parseable) + roster floor (>= 170 champs, cross-mode key parity) + artifact-absence
     (item 3508 and 6692 NOT in the first 3 of any comp-class cell for the flipped set: Miss
     Fortune, Jhin, Kai'Sa, Varus, Twitch, Jinx, Caitlyn). This is the RED-first signal - it
     fails loudly if a future table regresses to pre-dock content.
   - Layer 2 (slow, env-gated `RC_BUILD_ORDER_LIVE_PARITY=1`, needs :8893 up): for N sample
     champs (>= the 7 flipped crit-ADCs, both SR and ARAM), call
     `core.daemon_slayer_client.rank_for_primary_archetype` in-process (dock ON) at the
     generator's EXACT cell (level 11, target_armor 80 / mr 60 / max_hp 2000 / bonus_hp 600,
     `enemy_ad_share`/`enemy_ap_share` per comp-class) and assert the first 3 returned
     `item_id`s equal the committed table's first 3 for that cell. This is the true
     regen-parity proof that the committed data equals what the live dock produces.
   - Effective_score-parse pin (fast, server-free): assert
     `RankedItem.from_dict({..., "effective_score": 7.5}).effective_score == 7.5` so a future
     drop of `core/daemon_slayer_client.py:71` fails here, guarding the dock's engaged branch.
3. Close BACKLOG.md:13 OQ24 residual tail (2) and update docs/ORCHESTRATION_PLAN.md /
   ROADMAP.md to record the design answer (generator routes through the dock; backfill
   satisfied at 16.14.1; guard landed). Append the LEDGER entry at DONE.

## NON-SCOPE (do not touch)

- Family B tables: `data/daemon_slayer/build_orders/<patch>/build_orders_*.json` +
  `build_order_variants_*` via `core.build_order_precompute` / `core.build_order_variants`.
  DIFFERENT tool, DIFFERENT (display-keyed) keyspace, already regenerated R87 (LEDGER 881) and
  re-stamped/recomputed R119. Do NOT regen or conflate them here. (This is the family the
  build-coherence spec:227-230 pointed at; LEAP-04 is scoped to the enemy-comp-class Family A
  generate.py tool per BACKLOG:13 / OP:358.)
- No engine code, no scorer, no item-effect, no ENGINE_VERSION bump. The generator + engine
  logic are unchanged; this is the post-Step-1b follow-up regen the coherence spec prescribed,
  not a version change (bumping would be the R87 false-bump anti-pattern).
- No "engine variant" / no generator "re-route" (the OPEN Q branch that assumed a bypass - the
  design answer refutes it).
- No Share mirror change (Family A is RC-side data consumed by the coach, not part of the
  Share/src DS engine package).

---

## TESTABLE ACCEPTANCE CRITERIA (RED-first)

Write the guard test BEFORE the confirmatory regen so the RED/GREEN transition is observed.

1. RED-first artifact-absence (Layer 1, server-free): a fresh `git stash` of the guard test
   asserting "3508 and 6692 absent from first-3 for the 7 flipped champs" must PASS against
   today's committed 16.14.1 tables (they are already dock-correct). To demonstrate the guard
   has teeth, the test author temporarily injects a synthetic pre-dock cell fixture (MF
   balanced = [6692, 3508, ...]) and confirms the assertion FAILS on it, then removes the
   fixture. Document that RED demonstration in the test docstring.
2. Stamp assertions PASS: `version` == contents of `data/daemon_slayer/current.txt` (16.14.1);
   each file's `mode` matches its filename (`build_orders_sr.json` -> "sr", etc.);
   `generated_at` parses as ISO-8601 UTC.
3. Roster-floor PASS: each of the 3 tables has >= 170 champion keys and all 3 share the same
   champion key set (cross-mode parity), each cell a non-empty list of numeric-string ids.
4. Layer-2 parity PASS (env-gated, :8893 up): for each sample champ x comp-class x {sr, aram},
   `rank_for_primary_archetype(...)` first-3 `item_id`s == committed table first-3. Any
   mismatch is either a real stale table (regen + recommit) or a genuine parity break (stop and
   diagnose - do not paper over).
5. Effective_score-parse pin PASS: `RankedItem.from_dict` round-trips `effective_score`.
6. Confirmatory regen run: `--mode all` completes with non-empty tables (per-mode champ count
   >= 170, non-empty-cell count sane) and the diff vs committed is EITHER byte-identical
   (content) with only `generated_at` differing, OR a validated real diff that is committed.
7. Existing `tests/test_build_orders_generate.py` stays GREEN (schema / class-map / atomic-write
   / dry-run unchanged).

---

## R5 TIER

Nominal classification: Tier-2 (the output is DS-derived data from the engine + the coherence
dock). JUSTIFIED REDUCED SCOPE (generator-only + data regen; the "if generator-only + data
regen, justify reduced scope" allowance):

- No engine file, no scorer, no item-effect, no ENGINE_VERSION, no schema touched -> the full
  dual 20k suite / Tier-2 tax does not apply. This is data + one test module = effectively
  Tier-1.
- Verification actually run: the new guard module + `tests/test_build_orders_generate.py` +
  `pytest -k build_order` (build-order blast radius) + `py_compile` + `ruff` on the new test.
  NOT the DS-dir suite, NOT `tests/` in full.
- No Share mirror sync (Family A is not in Share/src).
- No DS :8893 restart OWED after (engine unchanged). BUT the engine MUST be UP and settled at
  the intended ENGINE_VERSION DURING the regen and the Layer-2 parity run (the generator
  refuses on a dead engine, tools/daemon_slayer_build_orders_generate.py:361; a mid-run bounce corrupts the table or fakes a
  parity mismatch).

---

## FILES TOUCHED

- REGENERATED (data, only if the confirmatory regen shows a real content diff):
  `data/daemon_slayer/16.14.1/build_orders_sr.json`,
  `data/daemon_slayer/16.14.1/build_orders_aram.json`,
  `data/daemon_slayer/16.14.1/build_orders_arena.json`.
- NEW test: `tests/test_build_order_generate_coherence_parity.py` (the two-layer guard +
  effective_score-parse pin). (Alternatively extend `tests/test_build_orders_generate.py`; a
  new module keeps the server-free schema tests cleanly separated from the env-gated parity
  layer.)
- DOCS at DONE: BACKLOG.md (close OQ24 residual tail 2), docs/ORCHESTRATION_PLAN.md +
  ROADMAP.md (record the design answer + guard), docs/LEDGER.md (append the entry).
- NO change to `tools/daemon_slayer_build_orders_generate.py`, `core/build_order.py`,
  `core/daemon_slayer_client.py`, or `core/build_planner/coherence.py` (they already route
  correctly - the design answer). Frozen-file list is not implicated.

---

## EST SESSIONS + MODEL

- EST SESSIONS: 1.
- MODEL: claude-opus-4-8, effort max (the parity reasoning + validate-before-trust-the-diff
  judgement warrant it, even though the mechanical footprint is small).

---

## DONE RITUAL

1. Ensure DS :8893 is UP and settled at the intended ENGINE_VERSION BEFORE the regen and the
   Layer-2 parity run. If the engine was bumped or the Share mirror synced recently, WAIT for
   the Share sync + DS restart to settle first - a mid-suite / mid-regen DS bounce produces
   false anchor-mismatch / parity failures that cost a re-run to confirm they were transient.
2. Run the guard test RED-demonstration, then the confirmatory `--mode all` regen, then the
   full guard test GREEN (Layer 1 + effective_score pin per-commit; Layer 2 with
   `RC_BUILD_ORDER_LIVE_PARITY=1` and :8893 up).
3. Re-verify fresh before claiming green: `pytest tests/test_build_order_generate_coherence_parity.py`
   + `tests/test_build_orders_generate.py` + `pytest -k build_order`; confirm the new test file
   exists on disk; report the exact pass/fail counts observed THIS run (do not carry a prior
   count forward).
4. Commit (regenerated data only if a real diff) + push. Update BACKLOG / ORCHESTRATION_PLAN /
   ROADMAP; append the per-item entry to docs/LEDGER.md (NOT CLAUDE.md). Confirm CI green.

---

## GHOST LIST (do NOT investigate / re-open)

- Kai'Sa Eclipse #6 light-dock CALIBRATION is a separate item (LEAP-07), NOT here. This item
  only confirms Kai'Sa's ER/Eclipse are absent from the first-3; the residual #6 Eclipse tuning
  is out of scope.
- Do NOT re-pitch a Stormrazor 3097 valuation dock - REFUTED (LEDGER 888 / BACKLOG:13 tail 1);
  3097 is a live, coherent Energized item on Aphelios/Zeri, not an artifact.
- The build_order no-double-unique-passive rule is ENGINE-authoritative - do NOT add a family
  map (a guard test fails on any family literal; core/build_order.py docstring, Settled list).
- Never `--force` a Meraki re-extract (the `latest` endpoint is mutable; Settled list).
- Do NOT regenerate or conflate Family B (`data/daemon_slayer/build_orders/<patch>/` +
  build_order_variants) - separate tool + keyspace, already done R87/R119 (NON-SCOPE).
- `tools/replay_build_order_validate.py` is a match-replay VALIDATOR (no `--static`, no table
  output) - it is NOT the regen tool and is not involved here.
- Do NOT bump ENGINE_VERSION (no engine logic changed - false-bump anti-pattern).
- Zeri Lich Bane / Liandry's AP-on-AD-marksman class is a distinct residual (BACKLOG:13 tail 4)
  - not this item.
- 7-bit ASCII only; no em/en dashes, no smart quotes.
