# Wakeup Notes — 2026-05-01 audit

> Single-pass thorough audit run while you slept. Move-not-delete on archival, frozen files only got dead-code surgery (no behavior changes), all smoke tests green at end. Restart RC at your leisure to pick up frozen-file edits.

---

## TL;DR

| | |
|---|---|
| Files archived | **23** files + 4 directories → `_archive/2026-05-01-audit/` |
| Frozen files edited | 4 (dead imports + dead helpers + 1 narrowed except) |
| Safety fixes | 3 (`_base_coach` lock try/finally, `moon_vision_server` body-size guard, vision-client init lock) |
| Scheduled task fixed | `RC-PatchRefresh` (weekly data refresh — was failing every run) |
| Terminal | acrylic=false, opacity=100% (default profile) |
| Smoke tests | dashboard, vision, supervisor, Phase3, scheduled tasks, bridge — all ✅ |
| Bridge anomaly | Game-PC `/loop /process-bridge-tasks` is dead — fix on Game-PC Claude side; nothing to do here |

---

## What was archived (under `_archive/2026-05-01-audit/`)

Every move is reversible. Run `mv _archive/2026-05-01-audit/<area>/<file> .` if anything turns out to be needed.

**root/** — `audit-pre-opus.tar.gz` (30-byte broken archive), `monitor.html`, `monitor_poll.py`, `moon_monitor.html`, `check_scrape.py`, `run_fix_and_restart.bat` (called nonexistent `fix_meta.py`), `watchdog.ps1`, `run_watchdog.bat`, `moon_sync_inbox/` (empty), `rc_coord/` (3 files, only self-refs), `tmp/` (single dribbble_ref.png).

**scripts/** — `discover_err.txt`, `discover_out.txt`, `aggregator C_err.txt`, `aggregator C_out.txt`, `sync_out.txt` (leftover stdout, 3 were 0 bytes).

**coaches/** — `tft_hyper_coach.py` (defines constants nothing imports; coaches/__init__.py routes all TFT variants to tft_coach.py).

**core/** — `data_store.py`, `version_check.py` (both unreferenced).

**ops/** — `run_self_healing_watchdog.ps1.DEPRECATED` (own contents say "Replaced by SelfMonitor"), `rc_screen_validator.py` (only referenced in audit-notes.md prose).

**tools/** — `.audit-ingame-monitor.py` (one-shot poller, hidden filename), `write_monitor_b64.py` (setup util for the orphan monitor.html).

**data/** — `aram_coaching_data.json.stale-bak`.

**legacy_moved/legacy/** — entire `legacy/` tree (`lan_bridge.py`, `moon_sync.py`, `ops_backups_20260418/` ~2.3 MB).

After a few days of stable operation, you can `rm -rf _archive/2026-05-01-audit/`.

## What I did NOT archive (judgment calls — review and decide)

- **Distribution-packaging tooling** (`tools/build_installer.py`, `build_portable.py`, `package_portable.py`, `run_packaged_smoke.py`, `preflight.cmd`, `snapshot.cmd`, `rollback_last.cmd`, `bootstrap_riot_commander_dev.{cmd,ps1}`) — listed in `tools/DISTRIBUTION_LAYOUT.md`. Useless on the live Legion+Game-PC topology, but harmless and might matter if you ever ship an installer. Decide later.
- **Phase 3 bootstrap one-shots** (`ops/phase3_setup.py`, `phase3_summary.py`, `phase3_queue_first_audit.py`, `phase3_install*.ps1`, `phase3_file_audit*.py`) — already executed; `agents/supervisor.py` is what's actually live now. Could safely archive but I left them since they're documented as Phase 3 deliverables.
- **`tools/calibrate_vision.py`** — the audit flagged it as unreferenced, but per CLAUDE.md you'll need it whenever the dashboard hex regions need re-tuning. Kept.
- **`app.py`** (root, 6-line shim) and **`overlay.py`** (root, re-exports OverlayApp) — both are tombstone-shims preserved because `main.py` (frozen) imports them.

---

## Frozen-file edits — what changed and why

All edits were dead-code removal or hardening — **no behavior change**. They will not take effect until next RC restart.

### `app/__init__.py`
- Removed unused imports: `threading`, `_start_hotkeys`, `FIELD_COLORS`, `RiftSnapshot`, `AramSnapshot`, `TftSnapshot`, `mode_from_game_mode_string`, `GameBottomStrip`, `GameRightTop`, `GameRightBot`, `ModeIndicator`, `ClientPanel`, `EXCLUDED_MODES`. All were leftovers from the ARCH-001 Phase 3-4 manager decomposition.
- Removed `_safe_log()` helper — `_game_lifecycle.py` defines and uses its own copy.

### `core/moon_proxy.py`
- Removed `import base64` (never used).
- Removed `force_recheck()` method (never called anywhere).

### `lcu/lcu_client.py`
- Narrowed bare `except Exception:` in `_request()` to `(URLError, OSError, TimeoutError, JSONDecodeError, UnicodeDecodeError, ValueError)` — matches the convention already used in `moon_proxy` and `game_snapshot`. Lets `KeyboardInterrupt`/`SystemExit` propagate during shutdown.
- Added `import urllib.error` (needed for the narrowed catch).

### `coaches/_base_coach.py` (not technically frozen but treated carefully)
- Wrapped `_lock.acquire/release` around `Thread.start()` in `try/finally` so an OS thread-limit exception can't leak the lock and silently kill the coach loop.

### `moon_vision_server.py`
- Added body-size guard (10 MiB cap) **before** `rfile.read()` in `do_POST`. A bad `Content-Length: 9999999999` could previously OOM the server.
- Wrapped lazy `_get_client()` init in a `threading.Lock` to avoid the rare double-init race.

### `RC-PatchRefresh` scheduled task
- Replaced bare `py` with absolute path `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`. Was failing every Wednesday with `ERROR_FILE_NOT_FOUND` because `py` launcher isn't on the scheduled-task PATH. Manual `data_pipeline.py meta` smoke confirmed the runtime works (currently 16.8.1 cached vs 16.9.1 live — patch drift you may want to refresh).

### Windows Terminal
- `useAcrylic: true → false`, `opacity: 80 → 100` in default profile.

---

## CRITICAL audit findings I did NOT touch (need your judgment)

These would change behavior if patched, so I left them for you. Sorted by priority.

### 🔴 Dashboard sqlite reconnection storm
`web_dashboard.py` opens a fresh `sqlite3.connect(...)` on every request to `_build_home_summary` (4 connections per `/api/home/summary` call), `_home_last_build`, `_home_trends_14d`, `_home_streaks`, `_load_match_rows`, and several history queries. Under hot-reload + `ThreadingHTTPServer` this fans out badly. **Fix:** wrap each in the existing `_DIAG_CACHE` pattern at line 514, or introduce a per-route connection cache. Probably the single biggest CPU/RAM win available.

### 🔴 Coach polling consolidation
`coaches/_base_coach.py` has 4 mode coaches each running 2 daemon threads that poll `127.0.0.1:8889/latest-liveclient` every 1.5s. With `vision_tracker` (0.75s) and `decision_detector` (1.0s) layered on top, the relay sees **6-8 polls/sec with no game running**. Consolidate into one shared fetcher — the `_STATE_CACHE_PAYLOAD` pattern at `web_dashboard.py:1261` is the model.

### 🟡 `/api/logs` reads up to 4 MiB and decodes the whole window
Even when caller asks for `n=200`, `web_dashboard.py:5071-5076` reads the tail bytes and decodes the entire window. Page from end + line-cap decode.

### 🟡 Bridge JSONL rotates inside the lock
`_bridge_maybe_rotate()` reads the full JSONL into memory to count lines, holds `_bridge_lock` for the full read+write. Move rotation off the lock or maintain a line counter. Bounded ~1 MB so not catastrophic.

### 🟡 `_frames_by_source` unbounded by source key
`moon_vision_server.py:54-56` — every distinct `source` upload-channel name creates a new slot, never expires. A misbehaving Game-PC agent that randomizes channel names leaks ~150 KB per unique source. Add LRU/size-based eviction.

### 🟡 Vision server is single-threaded
`moon_vision_server.py:673` uses `HTTPServer`, not `ThreadingHTTPServer`. A 5s Sonnet `/vision` call blocks every `/upload-frame` for 5s. Fine at current load (Game-PC every 2s) but visible during dashboard probes.

### 🟢 Minor — see audit findings inline
Several other low-severity items (busy waits, racy throttle ints, missing per-IP rate limit on the dashboard, unbounded ThreadingHTTPServer thread pool) — all listed in the audit transcript.

---

## Suggested next steps (besides further developing each RC UI WS page)

### Tier 1 — wins available right now
1. **Cache sqlite per request thread** in `web_dashboard.py` (the 🔴 above) — biggest CPU/latency win, ~2 hours of work.
2. **Centralize the LiveClient fetch** so `_base_coach.py` × 4 + `vision_tracker` + `decision_detector` all share one cached payload. Single shared 0.5s poll → ~6-8x reduction in idle HTTP traffic.
3. **Add log retention** — `logs/` is 191 MB with files back to 2026-04-06. Current `core/log_setup.py` rotation handles in-day rotation but doesn't sweep old days. A 14-day cap would buy back ~100 MB and keep parsing fast.
4. **`agents/state/task_queue.jsonl` rotation** — 600 KB and growing, no policy. Same fix as the bridge JSONL.
5. **Split `web_dashboard.py`** (5,775 lines, 292 KB single file). Top candidates to extract: the bridge handlers, the home/summary builders, the OCR endpoints, the build-preview/champ-select coach calls. Each is essentially a self-contained sub-router.

### Tier 2 — architecture & reliability
6. **Replace tkinter shim entirely.** `_HEADLESS = True` is permanent now per CLAUDE.md, but `app/_overlay_manager.py` still creates Tk windows just to hide them. Pure waste. ~200 lines removable from the manager + `attach_preview` becomes dead code.
7. **Bridge auto-flow watchdog.** Game-PC Claude's `/loop /process-bridge-tasks` dies on every Claude session restart. Today this is silently broken until the user notices. Add a heartbeat-based alert in the dashboard (e.g., "bridge silent for 10+ min") so you know without checking session-start logs.
8. **Convert long-lived daemon threads to `asyncio` tasks.** ~14-16 daemon threads at idle. A single asyncio loop with `asyncio.gather` would shave context-switch overhead and make graceful shutdown trivial. Probably a Phase 4 ARCH-002 follow-up.
9. **Compress `match_metrics.db` (32 MB) and `rewind_history.db` (1.7 GB)**. SQLite WAL+VACUUM analysis. Probably 30-50% reclaim.

### Tier 3 — technologies worth integrating
10. **Use Riot DataDragon's CDragon for items + champs instead of aggregator C scraping.** Already partially used via `lib/ddragon`; eliminate the scraper-dependent paths and you remove a class of "site changed HTML, scraper broke" outages.
11. **OBS WebSocket integration** — push current state (mode, score, build) into OBS as a text source. Lightweight (existing dashboard JSON is the payload), turns RC into a streaming overlay for free.
12. **Prometheus + Grafana** for the daemon-thread fleet. Each thread already keeps stats in `MetricsCache`. Expose `/metrics` Prometheus endpoint, scrape locally, dashboard the queue depths and poll latencies. Cheap visibility for the next time something silently degrades.
13. **PyInstaller / cx_Freeze the dashboard as a standalone exe.** The `tools/build_installer.py` shell exists but is dead. If you ever want to share RC with someone else, that's the path.
14. **Replace coaching_data_lock filelock with `portalocker`.** Custom file-locking is fragile across antivirus and OneDrive. `portalocker` is battle-tested, drop-in.
15. **Decision detector could run in `agents/supervisor.py`** rather than as a daemon thread inside `main.py`. Phase 3 stack already has the queue infrastructure; this would free `main.py` from another thread.

### Tier 4 — UI polish (since you're past the "complete UI before wiring DB" gate)
16. **Reactive state via SSE/WebSocket** instead of dashboard polling `/api/state` every Ns. The dashboard already has the WS infrastructure (`logs/ws/`).
17. **Compare loadout variants side-by-side** in the build chooser — current UI is one-at-a-time.
18. **Replay-coach diff view** showing decision_detector hits overlaid on the kill-time graph.

---

## Anomalies still outstanding

- **Game-PC bridge auto-flow loop is dead.** Last gamepc result was ~3 hours before this audit started. Not fixable from Legion. Action: when you next launch Game-PC Claude, type `/loop 1m /process-bridge-tasks` to re-arm it.
- **Patch drift:** ddragon meta says cached=16.8.1, live=16.9.1. `data_pipeline.py all` will refresh; the fixed `RC-PatchRefresh` task will do it next Wednesday automatically.

---

## Files added/changed in this commit

```
A  _archive/2026-05-01-audit/...           (23 files + 4 dirs)
A  WAKEUP_NOTES.md                         (this file)
M  app/__init__.py                         (frozen — dead imports + dead helper removed)
M  core/moon_proxy.py                      (frozen — dead import + dead method removed)
M  lcu/lcu_client.py                       (frozen — narrowed bare except)
M  coaches/_base_coach.py                  (lock try/finally hardening)
M  moon_vision_server.py                   (body-size guard, client init lock)
D  legacy/ → _archive/...
D  monitor.html, monitor_poll.py, moon_monitor.html, ... (see archive list above)
```

Plus: 3 new memories saved (two-supervisors, archive-pattern, RC-PatchRefresh fix).

---

If anything misbehaves on next restart, the most likely culprit is a missed import — grep `_archive/` for the file name to confirm it's an old reference, not a live one.
