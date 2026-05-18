# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-18 (done) — header-row-2 pill flicker: full bug-chain closed (e4b08ba c114e5b 00277c4 2329ebf, pushed)

Operator: "in pgl the 2nd row pills are switching on and off / occurs in other pages as well."

- **Root cause (don't re-investigate):** `body[data-mode]` flapped aram↔client ~1×/sec on the shared header. `/api/state.mode_key=aram` (correct s150 ARAM-lobby preflip via build_state.resolve_mode_key) drove `onState`→setMode("aram"); the WS `:8891/push` health envelope was **un-mirrored** (`aram_mode=False`) so `onHealth`→setMode("client"). Independent JS tasks → flap → every mode-gated row-2 pill flickered on every view.
- **`e4b08ba`** client fix: `onHealth` defers its "client" downgrade while `onState` recently asserted a preflip/in-game mode_key (8s staleness bound). `state.lastStateMode`/`Ts` added. Resilient regardless of server mirror. Replay: 41 flips/20 cycles → 1.
- **Server-side half:** the WS mirror (`file_ingest`) was dead because **RC-Phase3-Supervisor pid 5400 ran ~27h of pre-keystone-`3eb2e2d` code** (couldn't resolve queue 2400). Supervisor was *healthy*, not crash-looping — the anomaly's non-zero LastResult was a stale scheduled-task code. **Manually restarted it (pid 5400→17160); WS health now 17/17 mirrored.** `c114e5b` = file_ingest mirror regression test.
- **Regression (operator reported mid-session):** flap-fix made mode stably "aram" in lobby (by design), but the 4 row-2 pills were only mode-gated → showed on every page. **`00277c4`** view-gates ds/augments/trigger/nudge to `active-match` only (the s162 pattern, never extended to these 4).
- **Systemic gap fixed (frozen ops/rc_supervisor.py — operator-authorized):** **`2329ebf`** — `agents/supervisor.py` heartbeat now re-stamps a stable `started_at`; `_Phase3Watcher` restarts Phase-3 when `started_at` predates the newest import-chain mtime (agents/**/*.py + 4 cross-pkg files), via the existing cooldown+CircuitBreaker+schtasks path. Backward-compat (no started_at→skip), self-limiting, guarded. 24 watcher tests; verified vs live tree.
- **NEXT / activation:** `2329ebf` activates on the next RC-Supervisor restart (main watchdog) + next RC-Phase3-Supervisor restart (writes started_at). Acute issue already cleared (pid 17160). **Don't restart the top-level supervisor just to activate** — preventive + backward-compat; lands naturally on reboot/next deploy. Don't re-investigate the flap root cause or re-pitch a server-only fix; the client deferral is the durable backstop. Memory `reference_phase3_supervisor_stale_code.md` written.

---

# 2026-05-18 (done) — Mayhem augment recommender SHIPPED (10aa944, pushed)

CLAUDE #88 plan executed end-to-end (`Desktop/MAYHEM_AUGMENT_RECOMMENDER_PLAN_2026-05-17.md`). #88 flipped ✅ in CLAUDE.md + ROADMAP.

- **Task-1 gate (DON'T re-audit):** `match_history.db` = 13 augment-bearing matches, **ALL ARAM Mayhem (KIWI/2400), 0 Arena**. IDs = int `participant.stats.playerAugment{1..6}` (0=empty); win = `stats.win`; tracked via `raw_data.tracked_puuid`→participantIdentities. Substrate = `raw_data.lcu_match_detail` (NOT a stored `enriched` — that's a read-time `_enrich_from_lcu` transform). n_own≈0–2 → external prior dominates **by design** (Option B working, not a bug).
- **Shipped:** `core/augment_external_source.py` (Overlay App E Mayhem WR + cherry-augments.json meta cache; patch-pinned; degrade-on-outage; 199/199 ext↔cherry id reconcile; `_http_get` monkeypatch-able) · `core/augment_recommender.py` (Laplace `(w+α)/(g+2α)` + `n/(n+5)` pairwise synergy + §4 blend `w=n_own/(n_own+K)`; KIWI/CHERRY-filtered own scan; **row-count cache key = WAL-safe**, bug found+fixed via test) · `coaches/arena_coach.py` (`_augment_recommendation` + 2 splices in `_handle_augment_select`; parallel to Haiku, persists on Haiku outage) · `web/js/panels/item_build.js` (ranking+confidence in existing augments-pill tooltip; no reflow, idempotent). 33 new + 271 coach-sweep + 77 broader tests green; ruff clean; RC reloaded pid 7632 reload_ok=true.
- **Known/expected (DON'T "fix"):** Overlay App E `arena_augments` sibling = 0 usable rows → graceful neutral degrade. In scope: §4 locks Mayhem primary, 0 Arena own-data. Mayhem path fully works.
- **NEXT (operator-gated, not provable offline):** live Mayhem augment-select cross-check (OCR→rank vs pick made). Precondition: confirm League WindowMode in-client (fullscreen-lockup note). Recommender live in pid 7632; tooltip auto-serves via ADR-008.
- **#90 shared-primitive:** still its own scoped session; its Task-1 gate is now satisfied by this ship — `core/augment_recommender.py`'s Laplace/shrinkage is the concrete impl to generalize. Don't re-derive the augment data audit.

---

# 2026-05-17 (done) — #89 lobby change-mode FIXED + champ-select 920→2400 label sweep (c3a1e23, pushed)

ROADMAP #89 shipped off the s234 recon (recon was accurate; one staleness noted).

- **Mayhem 920→2400** (core bug — 920 = Poro King, Mayhem = 2400 KIWI): both pickers (index.html), agent `_LOBBY_QUEUE_NAMES`, `LV_QUEUE_TIPS`. Auto-serves from Legion via ADR-008 asset hash — no RC restart.
- **Silent-failure fix:** Home Find-Match picker swallowed every LCU result; both pickers now surface failures via `lcuPollResult`/`_lvQueueChangeError`. **Bespoke Arena/Mayhem create payloads deliberately NOT fabricated** (recon: must come from live capture) — the error-surfacing is what makes that one-shot capture possible.
- **Brawl 2300** dropped from agent lobby name-map (retired s214).
- **Arena 8×2 → 6×3:** LV tip, allyOpts cellCount, `_csvArenaPaneHtml` duo→trio, `_csvRenderEnemiesArena` slices (3→5 teams, 2→3 cells), 2 CSS grids.
- **Champ-select 920→2400 label sweep** (spawn-task follow-up, same commit): `_csvResolveRole` MAYHEM badge, `_csvQueueLabel`/`modeMap`, dev.js `_replayQueueLabel`; classifiers gain `q===2400`. **`cs.is_aram` rendering path untouched — item 87 preserved.**

**Don't re-investigate:** recon's "practice not special-cased in lobby-view dropdown" was stale — it already was; real defect = swallowed errors + 920 id (both fixed). **dashboard.js:5055** has the same `_replayQueueLabel` 920 bug but is confirmed-dead legacy — left alone.

**Verified:** py_compile + node --check clean; phase_b / snapshot / view_router / cs_retention suites green.
**Operator-gated NEXT (not provable offline):** live Practice/Mayhem/Arena lobby creation + Arena 6×3 visual + Mayhem-2400 switch. Agent name-map change (cosmetic label + Brawl) needs a Game-PC `C:\RC-Agent\` redeploy (offer bridge dispatch) — but the core Mayhem fix is JS/served-from-Legion, no redeploy needed. Precondition: confirm League WindowMode in-client (prior session's fullscreen-lockup note).
