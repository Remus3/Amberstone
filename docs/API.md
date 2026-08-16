# RC Dashboard API Reference

All endpoints served by `web_dashboard.py` on `:8888` HTTPS (Legion).
Pydantic schemas: `dashboard/api_schema.py` (outer shapes) - `core/coaching_payload.py` (coach field).
Ground truth = `dashboard/_dispatch.py` + each `dashboard/routes_*.py` module's
`GET_ROUTES` / `POST_ROUTES` registry (this file regenerated from that registry
2026-07-17, mdclean C5). Per-module roles: `docs/ARCHITECTURE.md` archmap.

---

## Core GET endpoints

| Path | Description | Schema |
|---|---|---|
| `/api/state` | Current coach payload + health + LCU snapshot (500 ms poll target) | `StateResponse` |
| `/api/state-stream` | SSE stream of `/api/state` on change (heartbeat every 15 s) | `StateResponse` events |
| `/api/health` | RC process health (`ops/runtime/health.json` + `rc_version`) | `HealthResponse` |
| `/api/health/all` | Consolidated rollup: RC + vision + DS + supervisor + cost | `HealthAllResponse` |
| `/api/ui-version` | SHA-1 hash of static asset mtimes (dashboard hot-reload trigger) | `{"v": str}` |
| `/api/asset-stamp` | Max mtime across `index.html`, `dashboard.css`, `main.js` | `{"mtime": float}` |
| `/api/cost` | Cost tracker state + daily spend | - |
| `/api/coach/trace` | Coach execution trace (last N calls) | - |
| `/api/coach/state` | Coach active/disabled state per mode | - |
| `/api/session/summary` | Current session summary (kills / deaths / gold delta etc.) | - |
| `/api/history?...` | Match history (query: `mode`, `limit`, `since_days`) | - |
| `/api/loadouts/all` | All stored loadout variants from `data/sr_user_builds.json` | - |
| `/api/home/summary` | Home-screen summary card (win rate, streak, recent matches) | - |
| `/api/replay/matches` | Replay-eligible match list from `rewind_history.db` | - |
| `/api/replay/match/<id>` | Single replay match detail | - |
| `/api/champions` | Champion list from `data/champion_profiles/*.json` | - |
| `/api/sr-draft/user-builds` | SR draft user build list | - |
| `/api/lcu-cmd-result` | LCU command last result | - |
| `/api/vision-state` | Vision pipeline state (tracker + last-frame age) | - |
| `/api/decisions` | Coaching decision ring (last 24 h) | - |
| `/api/decisions/log` | Extended decision log | - |
| `/api/decisions/heartbeat` | Decision-banner heartbeat | - |
| `/api/diagnostics` | Full system diagnostics dump | - |
| `/api/ocr` | OCR debug: run tiered OCR on latest frame | - |
| `/metrics` | Prometheus metrics (Counter / Gauge / Histogram) | text/plain |

## Panel / feature GET endpoints (module = `dashboard/routes_<name>.py`)

| Path | Module |
|---|---|
| `/api/aram-balance` | aram_balance |
| `/api/archetype-nudge` | archetype |
| `/api/ban-suggest` | ban_suggest |
| `/api/cc-blended-ehp-threat` | cc_blended_ehp_threat |
| `/api/cc-conditional-pressure` | cc_conditional_pressure |
| `/api/cc-pairing` | cc_pairing |
| `/api/champ-benchmarks` | champ_benchmarks |
| `/api/champ-select/adaptive-summoners` | adaptive_summoners |
| `/api/champ-select/ban-suggestions` | ban_suggestions |
| `/api/champ-select/counter-picks` | pickban |
| `/api/champ-select/personal-record` | pickban |
| `/api/champ-select/pickban-recs` | pickban |
| `/api/champ-select/spell-winrates` | adaptive_summoners |
| `/api/champ-select/team-damage-mix` | pickban |
| `/api/cs-archetype-pick` | archetype |
| `/api/damage-mix` | damage_mix |
| `/api/dictionary/{augments,champion-tags,items,runes}` | dictionary |
| `/api/draft-elo` | draft_elo |
| `/api/ds-combo` | ds_combo |
| `/api/ds-knobs` | ds_knobs |
| `/api/ds-matchup` | ds_matchup |
| `/api/ds-profile` | ds_profile |
| `/api/ds-relscore` | ds_relscore |
| `/api/ds-shape` | ds_shape |
| `/api/ds-skill-order` | ds_skill_order |
| `/api/ds-statcheck` | ds_statcheck |
| `/api/ds-sweep` | ds_sweep |
| `/api/duo-synergy` | duo_synergy |
| `/api/duration-winrate` | duration_winrate |
| `/api/item-wpa` / `/api/skill-wpa` / `/api/rune-wpa` / `/api/summspell-wpa` | *_wpa |
| `/api/last-match` | last_match |
| `/api/lcu/auto-accept` | auto_accept |
| `/api/loop-monitor` / `/loop-monitor` | loop_monitor |
| `/api/mains` / `/api/top8` | lobby_aux |
| `/api/op-score-curve` | op_score |
| `/api/peel-priority` | peel_priority |
| `/api/perf-curve` | perf_curve |
| `/api/personal-build` / `/api/personal-context` / `/api/personal-vs` | personal_* |
| `/api/player-profile` / `/api/player-snapshot` | player_* |
| `/api/post-game-rubric` / `/api/post-game-wpa` | post_game_* |
| `/api/rank-tier-bench` / `/api/role-bracket-bench` | bench_rank_tier / bench_role_bracket |
| `/api/replay/events` | replay_events |
| `/api/snowball-elasticity` | snowball_elasticity |
| `/api/spend/gates` | coach |
| `/api/spike-curve` / `/api/spike-markers` | spike_curve / spike_markers |
| `/api/team-context` | team_context |
| `/api/vision-frame` / `/api/vision-regions` / `/api/vision-reference-states` / `/vision-calibrator` | vision_calibrator |
| `/api/ward-heat` | ward_heat |

Static assets (`routes_static`): `/`, `/css/`, `/js/`, `/data/`, `/icons/*`,
`/agent/`, `/mock/`, `/manifest.json`, `/icon.svg`.

---

## POST endpoints

| Path | Body schema | Description |
|---|---|---|
| `/api/input` | `InputRequest` | Write `text` into `coaching_data.json.pregame` (coach reads next cycle) |
| `/api/command` | `CommandRequest` | Dashboard command: `force_vision` \| `refresh` \| `clear_pregame` |
| `/api/console-error` | `{kind, message, source, lineno, colno, stack, url}` | Relay browser JS errors to RC log (10 Hz server-side throttle) |
| `/api/analyze` | `{}` | Trigger Phase 3 supervisor analysis at `:8890` (synchronous, 30 s timeout) |
| `/api/ds-preview` | `DsPreviewRequest` | DS rank_for() top-8 items for a champion (champ-select overlay) |
| `/api/build-order` | `BuildOrderRequest` | Contextual DS-backed build-order plan |
| `/api/build-plan` | - | Build-plan panel payload (`routes_build_plan`) |
| `/api/aram-comp-verdict` | - | Deterministic ARAM comp-balance verdict |
| `/api/archetype-nudge/dismiss` | - | Dismiss the first-purchase mismatch nudge |
| `/api/cs-archetype-pick` | - | Store a champ-select archetype pick |
| `/api/coach-choice` | - | A/B tutoring-coach choice submit (`routes_coach_choice`) |
| `/api/coach/toggle` | `{enabled: bool}` | Enable/disable live coaching |
| `/api/champ-select-coach` | `{champion, allies, enemies}` | Trigger champ-select coaching |
| `/api/decisions/<id>` | `{choice}` | Record a coaching decision choice |
| `/api/decisions/respond_active` | - | Respond to the active decision banner |
| `/api/last-match/ingest` | - | Ingest the newest finished match |
| `/api/lcu-cmd` | `{command, args?}` | Send raw LCU command (admin gate) |
| `/api/lcu/auto-accept` | - | Toggle ready-check auto-accept |
| `/api/loadout/apply` | `{variant_id}` | Apply a saved SR loadout via LCU |
| `/api/loadout/list` | `{champion?, mode?}` | List available loadout variants |
| `/api/loadout/rune-pages` | - | Rune-page ops via LCU |
| `/api/scouting` | - | Player-scouting rank fan-out |
| `/api/speak` | `SpeakRequest` | TTS speak (voice coach) |
| `/api/sr-draft/apply` | `{profile_id}` | Apply SR draft coaching profile |
| `/api/sr-draft/user-builds` | `{builds: [...]}` | Save SR user build list |
| `/api/team-context/refresh` | `TeamContextRefreshRequest` | Force team-context recompute |
| `/api/top8` | - | Lobby top-8 refresh |
| `/api/vision-reference` / `/api/vision-regions` | - | Vision-calibrator reference/region writes |

---

## NOT on `:8888` - Mission Control (`:8895`)

These two live in `dashboard/routes_*.py` alongside the dashboard modules above, but
`dashboard/_dispatch.py` does NOT register them: `mc/routes.py` mounts them on the
Mission Control server (`mc/server.py`, `PORT = 8895`, tailnet + loopback). They are
listed here only so a reader who greps `dashboard/routes_loop_*` does not conclude
they are reachable on `:8888` - they are not.

| Path | Method | Module | Served by |
|---|---|---|---|
| `/api/loop-status` | GET | loop_status | `mc/routes.py` -> `:8895` |
| `/api/loop-control` | POST | loop_control | `mc/routes.py` -> `:8895` |

(`/api/loop-monitor` + `/loop-monitor` ARE on `:8888` - different module,
`dashboard/routes_loop_monitor.py`, registered in `_dispatch.py`.)

---

## Authentication

- **Dashboard endpoints**: no auth (local HTTPS, Legion-local only)

## Error shapes

All error responses: `{"error": "<message>"}` with an appropriate HTTP status code.
Success responses without a body: `{"ok": true}`.
