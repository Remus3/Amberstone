# RC Autonomous Audit + Refactor + Research - 2026-05-18

**Owner:** operator (SamplePlayer) - **Author:** overnight autonomous session
**Directive:** WAKEUP_NOTES.md "Part 2 - PIN: THE NEXT SESSION" (pre-authorized)
**Commit:** `9bba79a` (pushed `c2c4c3d..9bba79a main`) - all pre-approved authorizations honored.

ASCII-only per the hard rule. Spaced-hyphen for clause breaks.

---

## 0. TL;DR

A research subagent + a code-health audit subagent ran in parallel, then the
highest-leverage findings were implemented, fully tested, and shipped in one
commit. The headline finding was a **real live bug** (the in-game Build Chooser
threw a ReferenceError every render), not a stylistic nit. Net effect:

- 1 real bug fixed (Build Chooser ReferenceError).
- 558 lines of confirmed-dead code removed from `champ_select.js`.
- 2 robustness/drift safeguards added (bridge fail-soft, engine formula unify).
- 1 latent item-builder gap closed (`only_item_ids` carry-branch).
- +20 regression tests. Full suite **3516 -> 3536 passed, 0 failed**.
- ruff + py_compile clean; CI pushed.

Two larger items were **deliberately staged, not rushed** (dead `dashboard.js`
quarantine, and Phase 4(d) `unique_passive_key` exposure) - each has a precise
ready-to-execute spec in section 4. This was a scoped-grant judgment call, not
incompleteness: both are broad multi-file changes whose risk/budget profile did
not fit the tail of a long autonomous context, and the directive's own
guardrail is "surgical + tested + justified, the spirit of the frozen rule
still holds".

---

## 1. Competitive landscape research (2026)

Full per-competitor teardown was captured; condensed to the decision-relevant
core. Sources: aggregator A/aggregator G/overlay app E/aggregator C/aggregator B/overlay app F + 2025-26
entrants (Coaching App Z7, Overlay App Z6, the screen-aware-VLM wave: Hakko/Meeko/AICoach).

**What structurally favors RC (a local single-player tool):**

1. **First-principles item math is the moat.** Every competitor (Overlay App Z6,
   Aggregator B, Aggregator A, Overlay App E) ranks items by *winrate correlation*. Daemon Slayer
   computes per-champion ability-scaling DPS/EHP/burst/HPS vs actual enemy
   resists. Nobody ships real first-principles math at the build-recommend
   layer. lolmath.net is the only comparable, and it is a manual web tool
   with no live-game integration.
2. **Per-user model.** Competitors serve cohort averages throttled by Riot
   API limits at scale. RC owns the full local `rewind_history.db` and can
   compute the operator's *own* draft synergy / counter WR / pick-ban - a
   feature no SaaS can do per-user.
3. **Privacy + no ads + no Overlay Platform M bloat.** The single most consistent 2026
   complaint across Aggregator C/Overlay App E/Overlay App F is ad load, RAM, crashes.
   RC's tkinter-free headless-to-Chrome architecture is already the antidote.
4. **Real LCU depth without ToS-at-scale risk.** RC does authenticated
   lobby/champ-select/augment-intent reads that distributed products avoid.

**Prioritized opportunities (ranked by solo-operator leverage):**

| # | Opportunity | Status / leverage |
|---|---|---|
| 1 | **Surface the "why" of the math** ("+240 EHP vs their AP; BoRK +69 DPS vs their 2 tanks") on PGR + champ-select build chooser. A causal explanation Overlay App Z6/Aggregator B structurally cannot give. | Mostly built; needs UX surfacing. Phase 4(d) below directly serves this. |
| 2 | **Per-user draft/pick-ban model as a headline feature** in champ-select (your WR with/against, synergy with locked allies). | Backend exists (`rewind_history.db`, pickban route); needs foregrounding. |
| 3 | **Screen-aware VLM "what do you see right now?" on-demand coach.** The 2026 entrant wave converges here; RC owns the Sonnet pipeline + proven on-demand capture. One trigger -> one VLM pass -> coach-pill one-liner. | Infra owned; closes the most visible 2026 gap. Respect Riot "no decision-simulation". |
| 4 | **Arena/Mayhem augment recommender as a marketed pillar.** Overlay App Z6/Aggregator B/Overlay App E/Overlay App F all skip Arena/augments. `core/augment_recommender.py` already ships. | Uncontested niche; foreground it. |
| 5 | **aggregator-G-style 0-100 AI-Score + roster strip, computed locally.** Already the locked PGR design (RC heuristic, no Claude/Riot dep). | Scoped (ROADMAP S3). |
| 6 | **Local MCP server exposing Daemon Slayer + match DB.** Mirrors Aggregator A's Gaming Data MCP move; near-zero cost (engine already an HTTP service on :8893). | New, low-cost differentiator. |
| 7 | **State the anti-bloat architecture as an explicit design principle.** | Documentation/positioning. |

Skip: competing on breadth of static tier lists (Aggregator B/Aggregator A own scale RC
cannot match) and multi-game expansion. RC wins by being deep, local, and
mechanically correct for one operator.

---

## 2. Code-health audit - full findings

A read-only audit subagent reviewed ~520 project `.py` + the `web/js` tree.
Top 15 by leverage (HIGH/MED/LOW). Items marked DONE were shipped in
`9bba79a`; STAGED items have execution specs in section 4.

1. **HIGH - Build Chooser ReferenceError. DONE.** `item_build.js:361` called
   `_csDiffItemIds` which it never imported; `champ_select.js` defined but
   did not export it. Guaranteed `ReferenceError` every time the in-game
   Build Chooser rendered rows. Fix: extracted to shared
   `web/js/lib/items_index.js` as `diffVariantItemIds`, wired the live caller.
2. **HIGH - ~558 LOC dead orphan cluster in champ_select.js. DONE.** s208
   carry-forward confirmed zero-caller. Removed via an audit-gated atomic
   splice (guards assert the exact block boundaries before cutting).
3. **MED - `web/js/dashboard.js` (8531 LOC) entirely dead. STAGED.** Zero
   `<script>` ref in index.html, zero imports. BUT the audit's "lowest
   effort, just move it" was wrong: it has real coupling -
   `tests/test_champion_aliases.py:85` reads it as a "dead-code mirror",
   several `agents/agent3_testing/suite/test_round*.py` assert on its
   content, `agents/agent4_coach_mentor/ui_applier.py:33` allowlists it,
   `data/api_surface.csv` indexes it. Quarantining it blind would break
   tests. See spec 4.A.
4. **HIGH - Unguarded network + JSON parse in lessons_receiver. DONE.**
   `_fetch_bridge` did a bare urlopen + json.loads; any bridge outage or
   malformed response crashed `/process-incoming-lessons`. Now fail-soft
   to `[]`.
5. **MED - Duplicated League mitigation formula (engine drift). DONE.**
   `ability_dps._mitigation_factor._resist_factor` was a byte-identical
   copy of `dps._armor_factor`. Folded onto the single source of truth +
   a 7-test parity drift-guard. Proven behavior-preserving (full DS
   value-pinning suite stayed green) -> no ENGINE_VERSION bump / DS restart.
6. **MED - `effects.py` (5692 LOC) oversized. STAGED.** Engine correctness
   core; "works, biggest maintainability liability". Split the static
   item-effects data table out of the logic. NOT done autonomously -
   high-risk to the engine; needs a dedicated reviewed pass. Spec 4.C.
7. **MED - `adaptation_hint.py` (1602), `dashboard/builders.py` (1428)
   refactor candidates. STAGED.** Split along payload boundaries. Spec 4.C.
8. **MED - `agents/supervisor.py` (2312 LOC) oversized. STAGED.** Extract
   the watcher/circuit-breaker classes. Verify genuinely-not-frozen first.
9. **MED - `tools/gamepc_lcu_agent.py` (1945 LOC) oversized + deploy
   coupling. STAGED.** Careful - any split changes the Game-PC deploy unit.
10. **LOW/MED - 252 broad excepts. PARTIALLY DONE.** Most are deliberate
    documented defensive boundaries (acceptable per CLAUDE.md), NOT silent
    fault-hiding. Only the one clearly-warranted touch made:
    `bridge_monitor.py:86` bare `try:/except: pass` one-liner ->
    formatted + debug log. The rest reviewed and intentionally left
    (no-over-engineering; the audit itself said "not a blanket fix").
11. **LOW - `view_router_state.py` is a hand-maintained Python mirror of
    `main.js:_viewAutoDerive`. NOTED.** Currently in sync; documented
    drift hazard, not a defect. Recommend a CI cross-link check (spec 4.D).
12. **LOW - No `shell=True` / `os.system` anywhere. CLEAN (positive).**
13. **MED - Test-coverage gaps. PARTIALLY DONE.** Added
    `test_lessons_receiver_fetch.py` (covers #4 + the no-test gap) and
    `test_daemon_slayer_client_only_ids.py`. `dashboard/builders._enrich_from_lcu`
    LCU-parse coverage still a gap (spec 4.E).
14. **LOW - champ_select.js still ~2595 LOC post-cleanup. STAGED.** Split
    pickban + build-chooser sub-renderers later.
15. **LOW - Historical-narrative comment blocks bloat the largest files.
    STAGED** - trim during the #14 pass while files are open.

Longer tail: `core/moon_proxy.py` (FROZEN) has unguarded `json.loads` on
proxied responses - flagged only, not touched (frozen; needs explicit
approval). `routes_diag.py` / `routes_lobby_aux.py` json.loads - verify
enclosing try/except in a future pass.

---

## 3. What shipped this session (`9bba79a`)

| Change | File(s) | Test |
|---|---|---|
| #1 ReferenceError fix | `items_index.js` (+`diffVariantItemIds`), `item_build.js` (import+callsite+stale-guard cleanup) | node --check + 38 panel/view tests |
| #2 dead-code purge (558 LOC) | `champ_select.js` (3153 -> 2595) | snapshot_panels + view_router green |
| #4 lessons_receiver fail-soft | `core/lessons_receiver.py` | `test_lessons_receiver_fetch.py` (7) |
| #5 DS mitigation unify | `agents/daemon_slayer/ability_dps.py` | `test_mitigation_parity_audit_2026_05_18.py` (7) |
| only_item_ids carry-branch | `core/daemon_slayer_client.py` | `test_daemon_slayer_client_only_ids.py` (6) |
| #10 bridge_monitor logging | `core/bridge_monitor.py` | covered by existing monitor tests |

**Verification:** full suite `tests/ agents/daemon_slayer/tests/` =
**3536 passed, 778 subtests, 0 failed** (baseline 3516 + 20 new, zero
regressions). ruff clean, py_compile clean, pre-commit hooks green
(py_compile + archmap), CI pushed.

**Why no ENGINE_VERSION bump for #5:** the change is a provably
byte-identical refactor (the removed inner closure was line-identical to
`_armor_factor`). The full DS suite has thousands of exact DPS/burst/ability
value pins; all stayed green, which is a definitive equivalence proof.
Per the project's own precedent (ROADMAP item 85: "0 engine changes,
ENGINE stays, no DS restart" for behavior-neutral work), a no-op refactor
does not bump the version or require a `:8893` restart - the running
server's math is identical.

---

## 4. Staged work - precise execution specs

These are READY specs, not vague TODOs. Each is its own scoped `/clear`'d
session.

### 4.A - Quarantine dead `web/js/dashboard.js` (8531 LOC)

Genuinely dead at runtime, but coupled. Order of operations:
1. `tests/test_champion_aliases.py:85` - drop the `dashboard.js` entry from
   the mirror-list (its comment already calls it "dead-code mirror").
2. `agents/agent3_testing/suite/test_round{24,25,27,40,42}.py` - audit each
   `Path("web/js/dashboard.js").read_text()` assertion. Several are already
   stale (e.g. test_round40's "sim.js must load before dashboard.js" -
   sim.js was removed in s218). Remove or repoint to `main.js`/panels.
3. `agents/agent4_coach_mentor/ui_applier.py:33` - drop the
   `"web/js/dashboard.js"` allowlist entry + the dashboard.js-specific
   truncation guard (lines ~102-104).
4. `git mv web/js/dashboard.js docs/_archive/2026-05-18-dead-dashboard-js/`
   (quarantine pattern, reversible).
5. Regenerate `data/api_surface.csv` via `scripts/audit_api_surface.py`.
6. Trim the stale `dashboard.js` doc-comments in
   `web/css/panels/{primitives,map_state,header,bridge_pending}.css` and
   `web/index.html:428`.
7. Full suite must stay green.

### 4.B - Phase 4(d): expose candidate `unique_passive_key` on all rankers

Pre-approved per the directive + `BUILD_ORDER_PLAN_2026-05-17.md` 5(d).
Lets the shipped build-order card show the *positive* "locks Spellblade"
signal (today it only shows the *exclusion* signal post-hoc). Seam is
trivial - the value is already computed:

- `agents/daemon_slayer/rank.py:337` already computes
  `cand_key = cand_eff.unique_passive_key ...` and only surfaces it as
  `dead_unique_key` when it collides with an owned item. Add
  `unique_passive_key=cand_key` to the `RankedItem` construction (~:373),
  the `RankedItem` dataclass (after :81), and `to_dict()` (after :94).
- Mirror the same one-line addition in the other 5 ranker modules
  (`ehp.py`, `hybrid.py`, `ability_dps.py`, `burst.py`, `hps.py`) - each
  has the identical `cand_key`/`shares_dead_unique` pattern.
- Mirror `unique_passive_key: str = ""` + `from_dict` in the 6 client
  dataclasses in `core/daemon_slayer_client.py`, and add it to the
  `rank_for_primary_archetype` envelope rows (6 branches).
- `core/build_order.py` - consume it to label each slot's locked family.
- Tests + ENGINE_VERSION bump + DS restart (taskkill pid + relaunch
  `tools/start_daemon_slayer.py`, per memory) + full DS re-run.
- ~10 files, all additive (same wiring as the existing
  `shares_dead_unique`/`dead_unique_key` pair). Low design risk, broad
  mechanical surface - hence staged, not rushed at context tail.

### 4.C - Oversized-module refactor program (audit #6/#7/#8/#9)

In risk order (do the safe ones first; the engine last):
- `dashboard/builders.py` (1428) -> split by payload boundary
  (`builders_last_match.py`, `builders_home.py`, `builders_lcu_enrich.py`).
  Non-engine, well-tested surface - lowest risk.
- `coaches/adaptation_hint.py` (1602) -> split by concern.
- `agents/supervisor.py` (2312) -> extract `_Phase3Watcher` +
  `CircuitBreaker` into `agents/_phase3_watch.py`. Verify NOT frozen.
- `agents/daemon_slayer/effects.py` (5692) -> split the static
  item-effects registry into a versioned data module, leave `effects.py`
  pure logic. **Highest risk (engine correctness core) - dedicated
  reviewed session only, never autonomous.**

### 4.D - view_router drift CI guard (audit #11)
Add a CI check (or a cross-link comment in `main.js:_viewAutoDerive`)
pointing at the `dashboard/view_router_state.py` mirror so future editors
of either side are reminded. No runtime change.

### 4.E - `_enrich_from_lcu` parse coverage (audit #13)
`dashboard/builders.py._enrich_from_lcu` parses external/untrusted LCU
match JSON with many branches and no dedicated test. Add
`tests/test_builders_enrich.py` with representative LCU detail fixtures
(SR, ARAM Mayhem, Arena) asserting the enriched shape + graceful handling
of missing/odd fields.

---

## 5. Recommended next-session priority order

1. **Phase 4(d)** (4.B) - pre-approved, completes a shipped feature's UX,
   directly serves competitive opportunity #1 ("surface the why").
2. **dashboard.js quarantine** (4.A) - ~8500 LOC dead-weight removal,
   unblocks cleaner grep/maintenance.
3. **builders.py split** (4.C, lowest-risk slice) + 4.E coverage.
4. Competitive opportunity #2 (per-user pick-ban foregrounding) or #3
   (on-demand VLM coach) - product-level, operator-directed.
5. effects.py split (4.C) - only when there is appetite for a careful
   engine-internal session.

DS conditional-engine arc remains operator-CLOSED (s232) - not reopened,
not re-pitched.

---

## 6. Discipline notes

- Frozen-file edits: pre-authorized for this session but NONE were needed
  (`core/moon_proxy.py` json.loads flagged, not touched - the spirit of
  the frozen rule held).
- Every change is behavior-preserving or additive + fully tested. No
  blind redesigns. The two staged items were a deliberate scoped-grant
  judgment call, documented here so the decision is auditable.
- ASCII-only honored throughout (this file included).
- The Desktop deliverable is intentionally OUTSIDE the repo (hand-off
  artifact, same as `BUILD_ORDER_PLAN_2026-05-17.md`). README + BRIEF +
  WAKEUP + ROADMAP were synced in-repo separately.
