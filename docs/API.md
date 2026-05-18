# RC Dashboard API Reference

All endpoints served by `web_dashboard.py` on `:8888` HTTPS (Legion).
Pydantic schemas: `dashboard/api_schema.py` (outer shapes) · `core/coaching_payload.py` (coach field).

---

## GET endpoints

| Path | Description | Schema |
|---|---|---|
| `/api/state` | Current coach payload + health + LCU snapshot (500 ms poll target) | `StateResponse` |
| `/api/state-stream` | SSE stream of `/api/state` on change (heartbeat every 15 s) | `StateResponse` events |
| `/api/sim-state?scenario=<name>` | Sim scenario state from `data/sim_states.json` | - |
| `/api/health` | RC process health (`ops/runtime/health.json` + `rc_version`) | `HealthResponse` |
| `/api/health/all` | Consolidated rollup: RC + vision + DS + supervisor + cost + bridge + peers | `HealthAllResponse` |
| `/api/health/peer` | Peer health index (all known peers) | - |
| `/api/health/peer/<node>` | Single peer health record (`gamepc`, `peer`) | `PeerHealth` |
| `/api/ui-version` | SHA-1 hash of static asset mtimes (dashboard hot-reload trigger) | `{"v": str}` |
| `/api/asset-stamp` | Max mtime across `index.html`, `dashboard.css`, `dashboard.js` | `{"mtime": float}` |
| `/api/cost` | Cost tracker state + daily spend | - |
| `/api/coach/trace` | Coach execution trace (last N calls) | - |
| `/api/coach/state` | Coach active/disabled state per mode | - |
| `/api/session/summary` | Current session summary (kills / deaths / gold delta etc.) | - |
| `/api/history?...` | Match history (query: `mode`, `limit`, `since_days`) | - |
| `/api/loadouts/all` | All stored loadout variants from `data/sr_user_builds.json` | - |
| `/api/home/summary` | Home-screen summary card (win rate, streak, recent matches) | - |
| `/api/replay/matches` | Replay-eligible match list from `rewind_history.db` | - |
| `/api/replay/match/<id>` | Single replay match detail | - |
| `/api/recommend-champ` | Champion recommendation (DS + history) | - |
| `/api/logs` | Recent RC log lines (tail) | - |
| `/api/bridge` | Bridge inbox messages (`?since=<ts>&limit=<n>`) | - |
| `/api/bridge/messages` | Alias for `/api/bridge` | - |
| `/api/bridge/status` | Bridge connection + watcher status | - |
| `/api/bridge/cadence` | Bridge watcher cadence setting | - |
| `/api/preview-build` | DS build preview for a champion | - |
| `/api/champions` | Champion list from `data/champion_profiles/*.json` | - |
| `/api/sr-draft/user-builds` | SR draft user build list | - |
| `/api/lcu-cmd-result` | LCU command last result | - |
| `/api/vision-state` | Vision pipeline state (tracker + last-frame age) | - |
| `/api/decisions` | Bridge watcher decision ring (last 24 h) | - |
| `/api/decisions/log` | Extended decision log | - |
| `/api/diagnostics` | Full system diagnostics dump | - |
| `/api/reload-regions` | Reload `data/vision_regions.json` (no restart needed) | - |
| `/api/ocr` | OCR debug: run tiered OCR on latest frame | - |
| `/api/validate-ocr` | Validate OCR region coverage | - |
| `/api/ocr-crop?region=<name>` | OCR crop image for a named region | PNG |
| `/api/dev/vision-status` | Vision server diagnostic (frame age, tier counts) | - |
| `/metrics` | Prometheus metrics (Counter / Gauge / Histogram) | text/plain |

---

## POST endpoints

| Path | Body schema | Description |
|---|---|---|
| `/api/input` | `InputRequest` | Write `text` into `coaching_data.json.pregame` (coach reads next cycle) |
| `/api/command` | `CommandRequest` | Dashboard command: `force_vision` \| `refresh` \| `clear_pregame` |
| `/api/console-error` | `{kind, message, source, lineno, colno, stack, url}` | Relay browser JS errors to RC log (10 Hz server-side throttle) |
| `/api/analyze` | `{}` | Trigger Phase 3 supervisor analysis at `:8890` (synchronous, 30 s timeout) |
| `/api/ds-preview` | `DsPreviewRequest` | DS rank_for() top-8 items for a champion (champ-select overlay) |
| `/api/input` | `InputRequest` | Pregame text input |
| `/api/loadout/apply` | `{variant_id}` | Apply a saved SR loadout via LCU |
| `/api/loadout/list` | `{champion?, mode?}` | List available loadout variants |
| `/api/lcu-cmd` | `{command, args?}` | Send raw LCU command (admin gate) |
| `/api/bridge` | `BridgeInboxRequest` | Post a message to local bridge inbox |
| `/api/bridge/inbox` | `BridgeInboxRequest` | Receive cross-Claude bridge envelope (bearer-auth required) |
| `/api/bridge/cadence` | `{cadence: "active"\|"sleep"}` | Set bridge watcher poll cadence |
| `/api/bridge/pending/<id>` | `{action}` | Execute a pending bridge action |
| `/api/health/peer/<node>` | `{heartbeat: {...}}` | Publish peer health heartbeat |
| `/api/sr-draft/profile` | `{queue_id?, champion?}` | Get SR draft profile for current game |
| `/api/sr-draft/apply` | `{profile_id}` | Apply SR draft coaching profile |
| `/api/sr-draft/user-builds` | `{builds: [...]}` | Save SR user build list |
| `/api/replay-coach` | `{match_id}` | Run coaching analysis over a replay match |
| `/api/speak` | `SpeakRequest` | TTS speak (voice coach) |
| `/api/champ-select-coach` | `{champion, allies, enemies}` | Trigger champ-select coaching |
| `/api/coach/toggle` | `{enabled: bool}` | Enable/disable live coaching |
| `/api/experimental/get` | `{key}` | Get experimental feature flag |
| `/api/experimental/adapt` | `{key, value}` | Set experimental adaptation |
| `/api/experimental/mark` | `{key, outcome}` | Mark experimental outcome |
| `/api/aram-analyze` | `{state}` | Trigger manual ARAM analysis |
| `/api/decisions/<id>` | `{choice}` | Record bridge watcher decision choice |
| `/api/ocr-crop` | `{region}` | Return cropped OCR region image |

---

## Authentication

- **Dashboard endpoints**: no auth (local HTTPS, Game-PC secondary only)
- **`/api/bridge/inbox`**: `Authorization: Bearer <bridge_shared_secret>` from `ops/local_paths.json`

## Error shapes

All error responses: `{"error": "<message>"}` with an appropriate HTTP status code.  
Success responses without a body: `{"ok": true}`.
