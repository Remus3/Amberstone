# Riot Commander — Architecture

_Living document. Update after topology or module changes. See `docs/_archive/` for dated design docs._

---

## Machines

| Machine | Tailnet hostname | Tailnet IP | LAN IP | Role |
|---|---|---|---|---|
| **Legion** | `legion-rc` | `100.70.22.55` | `192.168.8.230` | RC main process, vision server `:8889`, web dashboard `:8888` |
| **Game-PC** | `gamepc-rc` | `100.95.66.128` | `192.168.8.237` | Runs League; Edge fullscreen on secondary display (1920×1280, 100% scale) |
| **Peer** | `peer-host` | `<peer-tailnet-ip>` | — | Cross-Claude peer; RC↔Peer bridge |

All three in tailnet `tailc150de.ts.net`. Prefer tailnet hostnames for all cross-machine HTTP.

Dashboard is viewed on Game-PC's secondary display (Duet iPad mirror). **iPad is a dumb monitor** — no PWA, no touch, no apps.

---

## Data flows

| From | To | Protocol | Purpose | Cadence |
|---|---|---|---|---|
| `gamepc_screen_agent` | `:8889/upload-frame` | HTTP POST (JPEG b64) | Screenshots for vision + OCR | every 2s |
| `gamepc_liveclient_relay` | `:8889/upload-liveclient` | HTTP POST (JSON) | Live game telemetry | every 1s |
| `gamepc_lcu_agent` | `:8889/upload-lcu` | HTTP POST (JSON) | Champ-select, queue, lobby state | every 1s |
| Game-PC `lcu_agent` | `:8889/lcu-cmd-pending` | HTTP GET | Drain queued commands | every 0.5s |
| Dashboard | `:8889/lcu-cmd` | HTTP POST | Queue a command for LCU (accept, bench, runes) | on user action |
| Browser (Edge) | `:8888/` | HTTP GET | Dashboard HTML + state polling | every 500ms |
| Claude sessions | `:8888/api/bridge` | HTTP POST + GET | Cross-Claude activity log | per prompt / daemon poll |

---

## Module map — Legion (`C:\Riot Commander\`)

### Orchestration (all frozen — do not edit without sign-off)
| File | Role |
|---|---|
| `main.py` | Entry point; starts RC |
| `app/__init__.py` | `OverlayApp` orchestrator; `tk.Tk()` root drives poll loops via `root.after()` |
| `app/_loop.py` | Async scheduler (post-tkinter-removal) |
| `app/_game_lifecycle.py` | Game start/end transitions, worker management |
| `app/_overlay_manager.py` | Mode switching (no UI overlays — legacy name) |
| `app/_state_authority.py` | `GameEnvelope` + envelope update/read paths |
| `app/_health_monitor.py` | Tk pulse + health state reporting |
| `app/_remediation.py` | DevRuntime remediation callbacks |

### Vision + data pipeline
| File | Role |
|---|---|
| `moon_vision_server.py` | `:8889` HTTP server — frame cache + Sonnet vision (701 LOC; god module candidate) |
| `game_reader.py` | Reads cached liveclient from vision server (1473 LOC; god module) |
| `core/game_snapshot.py` | Raw JSON → snapshot dataclass [FROZEN] |
| `core/vision_tesseract.py` | OCR pipeline (Tesseract) |
| `data/vision_regions.json` | OCR bbox calibration targets |

### Coaching
| File | Role |
|---|---|
| `coach_integration.py` | Haiku coaching dispatch + budget + cache (1217 LOC; god module) |
| `coaches/aram_coach.py` | ARAM + Mayhem mode — DS-before-Haiku |
| `coaches/arena_coach.py` | Arena mode — DS-before-Haiku |
| `coaches/brawl_coach.py` | Brawl mode — DS-before-Haiku |
| `coaches/tft_coach.py` | TFT Set 17 mode |
| `champion_profiles.py` | Static champion data (902 LOC; god module — extraction pending) |

### Dashboard
| File | Role |
|---|---|
| `web_dashboard.py` | `:8888` HTTPS server entry |
| `dashboard/_dispatch.py` | Route registration |
| `dashboard/_state_builder.py` | Builds `/api/state` payload |
| `dashboard/routes_bridge_pending.py` | `GET /api/bridge/pending` [FROZEN] |
| `dashboard/routes_health_peer.py` | `/api/health/peer` + `/api/health/all` |
| `dashboard/routes_metrics.py` | `/metrics` Prometheus |
| `dashboard/routes_dev.py` | Dev/sim panel endpoints |

### Core utilities
| File | Role |
|---|---|
| `core/log_setup.py` | Log init [FROZEN] |
| `core/moon_proxy.py` | Vision server proxy [FROZEN] |
| `core/prom_metrics.py` | Zero-dep Counter/Gauge/Histogram |
| `core/bridge_log.py` | In-memory + disk bridge log |
| `lcu/lcu_client.py` | LCU auth + command client [FROZEN] |

### Frontend
| File | Role |
|---|---|
| `web/js/dashboard.js` | Monolithic dashboard JS (8507 LOC; god module) |
| `web/css/dashboard.css` | Monolithic CSS (5812 LOC; god module) |
| `web/index.html` | Dashboard HTML (1362 LOC) |

---

## Game-PC agents (`C:\RC-Agent\`)

| File | Role |
|---|---|
| `gamepc_screen_agent.py` | 2s JPEG capture → POST `:8889/upload-frame` |
| `gamepc_liveclient_relay.py` | Live Client API polling → POST `:8889/upload-liveclient` |
| `gamepc_lcu_agent.py` | LCU auth + champ-select state → POST `:8889/upload-lcu` |
| `tools/gamepc_bridge_daemon.py` | Zero-cost bridge sentinel → headless `claude --print` |

---

## Daemon Slayer (`:8893`)

`agents/daemon_slayer/` — 547 item effects, ENGINE_VERSION 0.60.0, 911 tests. All 4 coach modes DS-before-Haiku. Ranks items by DPS math per champion before Haiku sees the prompt. See `docs/DAEMON_SLAYER.md`.

---

## God modules (pending decomposition)

| File | LOC | Plan |
|---|---|---|
| `web/js/dashboard.js` | 8507 | Phase 3 — ESM split |
| `game_reader.py` | 1473 | Phase 2.2 — split to `core/game_reader/` |
| `coach_integration.py` | 1217 | Phase 2.3 — split to `coach_integration/` |
| `champion_profiles.py` | 902 | Phase 2.1 — extract to `data/champion_profiles/*.json` |
| `moon_vision_server.py` | 701 | Phase 2.4 — split to `vision/` |

Full decomposition plan: `C:\Users\Administrator\Desktop\RC_FUTUREPROOFING_PLAN.md`.

---

## Key gotchas

1. **Riot's LCU + Live Client APIs are `127.0.0.1`-only.** Refuse LAN. Hence the Game-PC relay agent pattern.
2. **`iphlpsvc` portproxy self-loops on port 2999.** When Riot API stops responding, check `netsh interface portproxy show all` before anything else.
3. **`pythonw.exe` crashes silently on syntax errors.** Always `py_compile` before restart.
4. **`tk.Tk()` root in `app/__init__.py` is a scheduler, not UI.** Tkinter overlays were fully removed; `root.after()` drives the game polling loop. Full asyncio refactor is Phase T2 #8 (not started).
5. **Vision server content-type:** hardcodes `image/png`; screen agent sends JPEG. Magic-byte auto-detect `"image/jpeg" if data.startswith("/9j/") else "image/png"`.
6. **`os.replace` can raise WinError 5** when a reader has the target open. `atomic_write_json` uses 25/50/200ms retry-with-backoff. Don't hand-roll atomic writes.
7. **`pythonw.exe` PID ≠ child's reported PID under venv.** Supervisors latch `observed_pid` on first valid heartbeat; never match Popen pid.
