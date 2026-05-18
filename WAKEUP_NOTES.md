# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# 2026-05-17 — `open item research.txt` liftability-triage integrated (docs only, no code)

**Operator instruction:** implement the referenced multi-agent research methodology, run it on `Desktop/open item research.txt` (~90 links), triage NOW/FUTURE/CLOSED, "go over what to keep" → 3 decisions locked → integrate.

## Methodology (reusable — memory `reference_liftability_triage.md`)
s234 link-list triage + the two referenced agent memories (investigate-command: conditions+table+"no fixes yet"; parallel-batch-agents: subagents own slices, supervisor synthesizes). 6 parallel general-purpose slice agents (WebFetch + `gh`), fixed per-link schema: what-it-is / single-most-liftable-thing / RC-fit / license. Supervisor synthesized; agents proposed no fixes.

## 3 decisions LOCKED (don't re-litigate)
1. **Fold Morello** (`noaboa07/Morello`, **MIT**) `badges.ts` + `match-insights.ts` + 5-tab card → reference impl for the s220 PGR **0–100 score** + Deep-Review tabs.
2. **Shared smoothed-rate primitive** — ONE module (Laplace/Beta over own match DB; algo ref `Maelian25/lol-draft-prediction`, **no license → reimplement clean**) for #88 augment + pick/ban synergy + PGR score. Same family already locked for #88.
3. **101.qq.com** CN duo-synergy — worth a one-off Game-PC Network-tab capture (static `game.gtimg.cn` JSON; exact path needs the live capture).

## Integrated (docs only — `/done` will commit)
- `CLAUDE.md` new active-priority **#90** (full triage + 3 decisions + CLOSED corpus).
- `ROADMAP.md`: augment-recommender item cross-linked; new 🟡 **shared smoothed-rate primitive** + 🔵 **101.qq.com capture** one-off.
- `BACKLOG.md` "Research / inspiration": DDragon-mirror item annotated with vendor-safe tooling found (download-data-dragon Unlicense + get-league-patch MIT + Nyx0ra/lol-asset-downloader MIT + OriannaBot MIT); full FUTURE + CLOSED triage block appended.
- Memory: `project_lcu_pengu_pregame_postgame.md` findings appended (LCU corpus CLOSED, KebsCS still canonical, league_record=video-not-rofl); new `reference_liftability_triage.md` + MEMORY.md index.

## Don't-redo / NEXT
- **Don't re-research:** the 27-repo LCU corpus (zero lobby payloads anywhere — #89 needs live capture/KebsCS); ML/CV/voice/`riot-offline-mode` repos; `.rofl` (reinforced CLOSED).
- **NEXT:** shared-primitive build = its own `/clear`'d scoped session (Task-1 = the #88 data-audit gate already in ROADMAP). 101.qq.com capture = one-off Game-PC step. No RC code shipped — nothing to verify live.

## Game-PC (also this session — investigated live via :8892 MCP; memory captured)
- **ARAM-Mayhem match misbehaved:** operator moved the Duet display below-main, then League booted **exclusive-Fullscreen** → window vanished (alt-tab-out) → couldn't tab back. Recovered: taskbar-close → in-game leave-prompt → switch off fullscreen. **Not RC** (screen-agent disabled s221, no capture ran during web research). **Not the Vanguard 0x50 BSOD** (window lockup at match *start*, no crash). Captured: new `feedback_gamepc_league_fullscreen_lockup.md` + `reference_gamepc_monitor_index_volatility.md` updated (Duet now 1920×1280 @ y=1080 below main; resolution discriminator still valid 1080=game/1280=dash).
- **Game-PC daemons all UP** — verified live: gamepc_lcu_agent / liveclient_relay / hotkey / mcp_server / bridge_daemon all running, RC-BridgeDaemon task Running. Operator closed only Claude Code → **do NOT restart the daemons**; only a Game-PC Claude Code session needs reopening for `/process-bridge-tasks` autoflow.
- League persisted `WindowMode=2` (Windowed @1920×1080 main monitor) — safe (only exclusive Fullscreen=0 triggers the lockup). Re-verify the Window-Mode dropdown **in-client** before any live Game-PC test (PersistedSettings.json can overwrite game.cfg; League resets to Fullscreen on some patches/driver updates). This is now effectively a precondition for the #89 lobby-verify + Mayhem-recommender live runs.
