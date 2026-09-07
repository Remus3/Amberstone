# Mayhem/Arena Augment Recommender — Focused Session Scope

_Scoped 2026-05-17 from the pengu/research-list triage. Ready to execute in a fresh `/clear`'d session. One operator decision required before coding (§4)._

---

## 1. Goal & why

RC already **reads which augments are offered** in an ARAM-Mayhem / Arena picker via screen-OCR — proven live end-to-end, 2/2 Mayhem matches (CLAUDE.md item 86). Today the offered augments go to Sonnet via `arena_coach._AUGMENT_SELECT_PROMPT` and the model picks by judgment.

This session adds a **data-driven pick ranking**: given the 2–4 offered augments + the ones you've already taken this game, rank them by historical win-rate lift from RC's own match data. Closes the loop on the proven OCR path — OCR says *what's offered*, this says *which to take*.

The algorithm is lifted (re-implemented from scratch — `Mayhem-Doctor` has no LICENSE, so **algorithm only, do not vendor any file**) from `ReformedDoge/Mayhem-Doctor` `src/ui/augments.js`.

## 2. Already done — do NOT re-do

- Augment-OCR → coach path is **live and proven**. `coaches/arena_coach.py` already has `augment_select` / `augment_choices` state, `_augment_name_map()`, `_resolve_augment_apiname()`, stateful `_picked_augments`.
- The "no capture-free LCU augment API" conclusion is **re-confirmed** (KebsCS full client-26.05 catalog: zero `/lol-cherry/*`, zero `/lol-game-augments/*`). **Do not re-pitch an LCU augment API.**
- Continuous DXGI screen-agent is **BSOD-confirmed disabled**. Capture stays operator-gated. **Do not re-enable it.**

## 3. Data substrate (verify in Task 1 — paths from a 2026-05-17 grep, not yet line-confirmed)

- **Offered augments at pick-time:** `state["augment_choices"]` + `state["augment_select"]` flag — already populated by vision OCR, consumed in `coaches/arena_coach.py` (~L380). The recommender hooks in *here*.
- **Historical outcomes:** `match_history.db` LCU-ingest → `enriched.roster[].augments` (list of augment **IDs**, per player) + per-match win flag. Parsed in `dashboard/builders.py` (`_enrich_from_lcu`, ~L684 hero `arena_augments`, ~L722 per-player roster `augments`, s219 v7 — covers Mayhem KIWI + Arena).
- **Augment metadata:** RC's per-patch `arena_augments.json` (display↔apiName). **New lift:** also cache `/lol-game-data/assets/v1/cherry-augments.json` (static LCU asset) → authoritative id→name/icon/**rarity** (`kSilver/kGold/kPrismatic`); RC's current file may lack rarity.

## 4. Cold-start / sparsity — DECISION LOCKED: Option B (external-seed)

_Operator chose **Option B** 2026-05-17. The recommender bootstraps from an external Mayhem/Arena augment win-rate source, then blends toward RC's own ingested history as it accumulates. Do not re-deliberate this; execute B._

**Blend mechanic:** per augment, `score = w·own_WR + (1−w)·external_WR` where `w = n_own / (n_own + K)` (reuse the same `n/(n+5)`-style shrinkage, K tunable). With zero own games the rec is 100% external prior; it shifts to own-history smoothly as ingest grows — no hard threshold, no silent-below-N gate (that was Option A).

**EXTERNAL SOURCE — VALIDATED & LOCKED 2026-05-17** (operator-provided, validated against the criteria; this sub-task is CLOSED — do not re-research):

- **Endpoint:** `GET https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/aram_mayhem_augments` (overlay-app-e.gg's data backend). **Unauthenticated**, no params, `access-control-allow-origin: *`, BunnyCDN-cached (~1h). The `overlay-app-e.gg` HTML is bot-protected; this data host is **not** — plain `GET`, no browser/JS-render needed.
- **True ARAM-Mayhem data** (not an Arena proxy). Arena fallback sibling if ever needed: `.../prod/lol/arena_augments`.
- **Fields:** per augment — `augment_id` (numeric string = **Riot augment id, maps 1:1 to `cherry-augments.json` `id`** — no name fuzzy-matching), `stats{win_rate, pick_rate, num_games, num_win_games, tier}`, `augment_stage_stats[]` (per Mayhem round 1–5), `top_champions[]` (per-champ WR). `patch` field present (e.g. `"16.10"`); `dt`/`generated_at` show ~daily refresh; huge samples (100k–650k games/augment; 199 augments).
- **Important blend nuance:** this source gives a per-augment **marginal WR prior only** — it has **no augment-pair synergy** (champion co-occurrence only). So: the §4 blend (`w·own + (1−w)·external`) applies to the **per-augment marginal score**; the **pairwise/co-occurrence lift stays own-history** (Mayhem-Doctor `n/(n+5)`), and is simply absent at cold-start (acceptable — marginal WR is the dominant signal; per-round `augment_stage_stats` can optionally sharpen the prior).
- **Caveats to design around (not blockers):** undocumented private API (URL pattern could change without notice); ToS unreviewed. Mitigate: defensive fetch + **patch-pinned cached snapshot** (degrade to last-known prior on outage; degrade to the existing LLM `_AUGMENT_SELECT_PROMPT` path if there is no prior at all). Refresh trigger = patch flip (same as the DDragon mirror); the endpoint's own `patch` field tells you the data's patch.

## 5. Session task list (ordered — Task 1 gates the rest)

1. **Data audit (gating).** Count `match_history.db` matches with non-empty `enriched.roster[].augments`, split by mode (Mayhem KIWI 2400 / Arena CHERRY). Confirm augment-ID field shape + win derivation. Confirm the `arena_coach` ~L380 hook point + `builders.py` ~L684/722 line numbers. Establishes the `n_own` reality the §4 blend weight depends on.
2. **External-source fetcher** (source already validated & locked — §4). Build the cached, patch-pinned fetcher for `https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/aram_mayhem_augments` (plain GET, atomic snapshot per patch, degrade to last-known on outage). Parse `stats.win_rate` + `num_games` per `augment_id`; keep `augment_stage_stats` for optional round-aware priors.
3. **Static asset cache.** Fetch + cache `cherry-augments.json` (atomic write, per-patch dir alongside `arena_augments.json`). id→{name, icon, rarity}. Reconcile OCR display-name → id against this + RC's existing map + the external source's augment keys.
4. **Recommender core** (new module, e.g. `core/augment_recommender.py`). Re-implement: Laplace-smoothed per-augment WR; pairwise co-occurrence lift with `n/(n+5)` shrinkage; greedy synergy conditioned on `_picked_augments`. **§4 blend:** `w·own + (1−w)·external`, `w = n_own/(n_own+K)`. Input: offered IDs + already-picked IDs. Output: ranked list with blended score + `n_own` + blend-weight surfaced.
5. **Wire into `arena_coach`.** At the augment-select branch, call the recommender; always emits (external prior covers cold-start — no silent gate). Keep the LLM `_AUGMENT_SELECT_PROMPT` path intact as a parallel signal, not a fallback.
6. **Surface.** Minimal: blended ranking (with confidence = blend weight) where augment advice already renders (coach output / dashboard augment panel). No new page.

## 6. Tests + live verification

- Unit: recommender math (Laplace, shrinkage, greedy) on synthetic match sets; **§4 blend** — `w=0` (zero own → 100% external prior), `w` mid (mixed), `w→1` (own dominates); external-source-down → last-snapshot prior path.
- Asset: `cherry-augments.json` fetch/cache/parse + id↔name reconciliation against `arena_augments.json`; external-source parse + patch-refresh + snapshot-fallback.
- Integration: `arena_coach` augment-select branch emits a ranking (or correctly stays silent) given stubbed `augment_choices`.
- Live: next operator-gated Mayhem/Arena match — OCR detects offered augments → recommender ranks → cross-check the pick made vs the rec. Per-page UI-audit ritual if a panel changes.

## 7. Non-goals / don't-redo

- No LCU augment API (dead — item 86, KebsCS-confirmed).
- No continuous screen-agent (BSOD).
- No new Replay/Deep-Review page (.rofl confirmed dead-end 2026-05-17 — BACKLOG).
- Don't vendor Mayhem-Doctor files (no license) — re-implement the algorithm.

## 8. Engine/restart notes

Recommender is RC-side (not the DS `:8893` engine) → no ENGINE_VERSION bump, no DS restart. RC supervisor picks up new code via `restart_trigger.txt` after commit; verify `health.json` new pid + `last_reload_ok=true`.
