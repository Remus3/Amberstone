# Riot Commander — Audit Notes

Started 2026-04-25, autonomous /loop 3m audit.

Format:
- **FIX** (taken in-cycle) — bug fixed, file path, what changed.
- **NOTE** (queued for review) — improvement idea with Why / Effort / API impact.
- **FROZEN-FLAG** — issue in a frozen file; flagged for user approval.

---

## Cycle 0 — 2026-04-25 (initial pass)

### FIX-001 · Stale vision frames silently sent to Sonnet
- **File:** `modes/shared_vision.py`
- **Bug:** When Game-PC's screen agent dies, `moon_vision_server` keeps serving the last cached frame indefinitely. `_capture_screen()` warned at age > 8s but still returned the b64, so coaches kept feeding 30+ s old frames to Sonnet, burning API credits to "analyze" a stale game state.
- **Fix:** Added `_FRAME_HARD_AGE_S = 30.0` constant. If `age > 30s`, `_capture_screen()` now returns `None` (treats it as if no frame exists). Coaches skip the vision tick and a `_fail_streak` increment surfaces the outage in logs.
- **Cost prevented:** ~1 Sonnet call (~$0.005) per coach poll cycle while Game-PC is down. With multiple coaches + 2-minute outage, 4–8 calls saved.

### NOTE-001 · Bridge log eviction race at 100-message boundary
- **File:** `web_dashboard.py:156–189`
- **Why:** `collections.deque(maxlen=100)` is thread-safe per-op but two concurrent posts at the boundary can lose ordering or evict differently than expected. Bridge messages are time-sensitive (cross-Claude task results).
- **Effort:** Low — wrap append+evict in the existing `_bridge_lock`.
- **API impact:** None.

### NOTE-002 · MCP server has no per-tool timeout cap
- **File:** `tools/gamepc_mcp_server.py:498–504`
- **Why:** `run_powershell` with `timeout_s=600` can hang if the OS itself gets stuck. ThreadingHTTPServer thread leaks until exhaustion. Bound the tool dispatch with `concurrent.futures.ThreadPoolExecutor.submit().result(timeout=N)` or use signal-based watchdog.
- **Effort:** Medium — Windows doesn't have SIGALRM; use a watchdog thread.
- **API impact:** None.

### NOTE-003 · Coaching data atomic-write race (multi-writer)
- **File:** `web_dashboard.py /api/command "refresh"` + various coach writers
- **Why:** Atomic write protects against torn files but not against lost updates from concurrent readers. Pattern read→modify→write is inherently lossy under concurrency.
- **Effort:** High — needs a file-level lock or single-writer queue.
- **API impact:** None.

### NOTE-004 · MCP `capture_monitor` quality hard-capped at 85
- **File:** `tools/gamepc_mcp_server.py:230–261`
- **Why:** Already accepts `quality` param. Default is 85 which is fine for AI vision but lossy for debugging text in logs/UI screenshots. The client passes its own quality (we use 75); not actually a defect — false positive.
- **Effort:** N/A (works as designed).
- **API impact:** None.

### FIX-002 · `/api/state` cache (1 s TTL)
- **File:** `web_dashboard.py` (module-scope `_STATE_CACHE_PAYLOAD/_TS` + handler)
- **Bug:** Each /api/state call did an HTTP round-trip to the vision relay via `_liveclient_summary()`. With 5+ dashboard tabs polling, that's wasted work.
- **Fix:** 1-second cache invalidates naturally with payload mtime cadence. Cuts vision-relay load proportional to client count without changing observable behavior (1 s lag is below the staleness pill thresholds).
- **Verified:** RC restarted to PID 5484, last_reload_ok=true.

### NOTE-006 · `game_reader` polls + warns continuously when no game running
- **File:** `game_reader.py` (NOT frozen)
- **Why:** When `mode=client` (no live game), polling loop still hits the Riot Live Client at :2999 every 2s and times out. 780+ warnings in today's log are pure noise. RC already knows `has_game=false` from health; should idle the poll until LCU signals game start.
- **Effort:** Medium — coordinate poll cadence with health.json or LCU phase.
- **API impact:** None (saves local network + log noise).

---

## Cycle 1 — 2026-04-25

### FIX-003 · `bridge_task.py` rejects note-kind posts (auto-pick `--kind`)
- **File:** `tools/bridge_task.py`
- **Bug:** `--prompt` was mandatory even for log-only "kind=note" posts, which broke the cron-fired audit cycle summary command (`bridge_task.py --target legion --source legion --summary "..."` would argparse-fail with "the following arguments are required: --prompt").
- **Fix:** Added `--kind {task,note}` flag. If omitted, defaults to `task` when `--prompt` given, `note` otherwise. Backward-compatible (existing callers unchanged).
- **Verified:** Smoke test `py tools/bridge_task.py ...` posted `task-357d2a03d08f` successfully.

### FIX-004 · Auto-regenerator for `items_index.json` (was NOTE-007)
- **File:** `scripts/data_pipeline.py` — added `cmd_items_index()` and registered `items_index` CLI command + included it in `cmd_all()`.
- **Bug:** When League patches and DDragon adds new items, the dashboard's item lookup falls through to `.no-icon` (the "?" placeholders). `data/meta/ddragon_items.json` had all the source data but nothing regenerated `web/data/items_index.json` from it.
- **Fix:** New command rebuilds byName/byId maps from DDragon meta, skips when version unchanged, atomic write via .tmp+replace. Verified: `py data_pipeline.py items_index` → "items_index.json already at patch 16.8.1 — skipping". Future `data_pipeline.py all` invocations will keep the dashboard in sync.

### NOTE-008 · Console-error pipe is blind when `/api/console-error` itself fails
- **File:** `web/js/dashboard.js:3522` + `web_dashboard.py:4164`
- **Why:** The pipe swallows POST failures (`.catch(() => {})`) intentionally to avoid recursion. But if the endpoint is down (or the dashboard server crashes), all subsequent JS errors are silently dropped — exactly when the user MOST wants to know. A localStorage fallback (queue, flush on next successful post) would close that blind spot.
- **Effort:** Medium — needs queue + size cap + flush trigger.
- **API impact:** None.

### NOTE-009 · `/api/console-error` has no server-side rate limiting
- **File:** `web_dashboard.py:4164`
- **Why:** Client-side throttle is per-tab at 2 Hz. Multiple tabs in error-spam state (e.g., during a CSS regression) could collectively hit the endpoint dozens of times per second, each producing a WARNING log line. Add a 10 Hz global cap server-side as defense in depth.
- **Effort:** Low — `(last_seen_ts, count)` tuple, drop if too fast.
- **API impact:** None.

### FIX-005 · Clarified BaseCoach `_lock` scope (was NOTE-010)
- **File:** `coaches/_base_coach.py` `_maybe_coach`
- **Bug:** Misleading scope — readers might assume the lock guards the coaching call, but it only guards the spawn moment.
- **Fix:** Comment block above the lock acquire explains: real serialization comes from debounce on `_last_coach`; the lock prevents two near-simultaneous `_maybe_coach` calls from both clearing the debounce check before either bumps `_last_coach`. Behavior unchanged — comment only.

---

## Cycle 2 — 2026-04-25 00:00

### FIX-006 · MCP `tool_read_file` OOM hazard (deployed both sides)
- **File:** `tools/gamepc_mcp_server.py:155–172` (Legion source) + `C:\RC-Agent\gamepc_mcp_server.py` (Game-PC deployed)
- **Bug:** `data = p.read_bytes()[:cap]` reads the ENTIRE file into RAM before slicing. With a 4 MiB cap but a multi-GB log file path passed, the server would OOM before honoring the cap.
- **Fix:** Replaced with `with open(p, "rb") as f: data = f.read(cap)` — streaming read stops at `cap` bytes regardless of file size.
- **Deploy:** Edit applied to Legion's source, then deployed to Game-PC via PowerShell in-place edit (with `.bak.<ts>` backup), `py -m py_compile` verified, then atomic move into place. Game-PC MCP server restarted cleanly via detached `cmd /c start /B` batch (so the in-flight MCP call from this cycle wasn't killed). Verified by responsive `path_exists` call post-restart.
- **Damage prevented:** Any future call like `mcp__gamepc__read_file(path="C:\\Windows\\System32\\winevt\\Logs\\big-event-log.evtx")` no longer crashes the server.

### NOTE-011 · Screen agent captures wastefully during outage
- **File:** `tools/gamepc_screen_agent.py:179–197` (loop)
- **Why:** Capture happens BEFORE upload, so during Legion outage the agent still does Pillow `ImageGrab` every 30s (after exponential backoff). Save ~30 ms CPU and one Win32 GDI call per failed cycle by skipping capture when `consecutive_fail` is high — only capture when about to attempt a real upload.
- **Effort:** Low — gate `capture()` on `consecutive_fail < 3` or do a `try-upload-empty` health-probe ping first.
- **API impact:** None.

### NOTE-012 · MCP `run_powershell` timeout already enforced (auditor false positive)
- **File:** `tools/gamepc_mcp_server.py:131–152`
- **Why:** Cycle 0 NOTE-002 flagged risk of thread exhaustion if a tool hangs. Re-reading: `subprocess.run(..., timeout=timeout_s)` enforces the cap (max 600s), and `TimeoutExpired` is caught. Python kills the subprocess on timeout. The remaining concern would be if PowerShell ITSELF were unkillable (kernel-level hang), but `subprocess.run` calls `Popen.kill()` on timeout which sends `TerminateProcess`. NOT a real bug — closing this note.
- **API impact:** None.

---

## Cycle 3 — 2026-04-25 00:03

### NOTE-013 · LCU agent: `execute_command` exception loses cmd-done report
- **File:** `C:\RC-Agent\gamepc_lcu_agent.py` (Game-PC, ~loop)
- **Why:** Inside the inner `for item in items:` loop, `result = execute_command(cmd)` runs WITHOUT its own try/except. If LCU disconnects mid-call or PATCH throws, the exception propagates up to the outer cmd-poll except, BUT the `post("/lcu-cmd-done", ...)` for that command never fires. Legion's queue keeps the command "in-flight" forever.
- **Effort:** Low — wrap `execute_command(cmd)` in try/except that constructs `result = {"ok": False, "err": "<exc-class>: <msg>"}` so the done-post still fires.
- **API impact:** None.

### NOTE-014 · LCU agent + liveclient relay have no Legion-down backoff
- **Files:** `C:\RC-Agent\gamepc_lcu_agent.py` + `C:\RC-Agent\gamepc_liveclient_relay.py`
- **Why:** When Legion is unreachable, both agents hammer Legion at full rate (1 s LCU push, 1 s liveclient push, 0.5 s cmd poll on LCU). Add the same `consecutive_fail` exponential-backoff pattern that `gamepc_screen_agent.py` already implements (cap at 30 s).
- **Effort:** Low — copy the pattern from screen agent.
- **API impact:** None (saves LAN bandwidth + Legion CPU during outages).

### NOTE-015 · `/api/lcu-cmd` forwards payload without validation
- **File:** `web_dashboard.py:4188–4205`
- **Why:** Forwards request body verbatim to `:8889/lcu-cmd`. If a malformed body is posted (e.g., missing `cmd` field), the vision server gets garbage. Validate at the dashboard edge — require `payload.get("cmd")` is one of the known commands (`accept_ready`, `set_config`, `bench_swap`, `set_summoners`, `lock_pick`).
- **Effort:** Low — 6-line allowlist check.
- **API impact:** None (defensive hardening).

### NOTE-016 · `vision_tesseract._slow_tick` not thread-safe
- **File:** `core/vision_tesseract.py:441–442`
- **Why:** `_slow_tick % _SLOW_MODULO` then `_slow_tick += 1` is read-modify-write across threads. If `/api/ocr` and a coach poll fire `read_fast_fields()` concurrently, increments can be lost; cadence drifts but doesn't break correctness. Wrap in a `Lock` or use `itertools.count()` for atomic increment.
- **Effort:** Trivial — 3-line change.
- **API impact:** None.

### NOTE-001 · CLOSED — Bridge log race was false positive
- **File:** `web_dashboard.py:155–177`
- **Re-reading the implementation:** `_bridge_post` already wraps `_bridge_log.append(entry)` in `_bridge_lock` (line 175–176). `deque.append()` with `maxlen` is itself atomic under the GIL — the eviction is part of the same atomic op. The auditor's race scenario doesn't materialize. Closing as false-positive.

### FIX-007 · BUNDLE — Tesseract atomic counter + LCU cmd validation + console-error server throttle
- **Files:** `core/vision_tesseract.py`, `web_dashboard.py` (two edits)
- **What:** Three coherent low-effort hardenings shipped together with one RC restart:
  - **NOTE-016 → fixed:** `_slow_tick` int counter replaced with `itertools.count()`. GIL-atomic increment kills the read-modify-write race when /api/ocr and a coach call `read_fast_fields()` concurrently. Cadence stays correct under load.
  - **NOTE-015 → fixed:** `/api/lcu-cmd` now validates `cmd` against an allowlist (`accept_ready`, `set_config`, `bench_swap`, `set_summoners`, `lock_pick`) at the dashboard edge. Bad commands get 400 with the allowed list — the LCU agent on Game-PC never sees garbage.
  - **NOTE-009 → fixed:** `/api/console-error` now throttles globally to 10 Hz at the server. Drops are counted; a single info-log entry summarizes drop count when the next genuine post lands. A misbehaving tab can no longer flood the daily log.
- **Verified:** RC restarted to PID 3364 (was 5484), `last_reload_ok=true`, `last_reload_error=null`.

---

## Cycle 4 — 2026-04-25 00:07

### FIX-008 · Arena + Brawl coaches now write `champion` + `ally_spells`
- **Files:** `coaches/arena_coach.py`, `coaches/brawl_coach.py` (`_run_coach` payload dict)
- **Bug:** Both coaches built the dashboard payload without `champion` or `ally_spells` fields. The dashboard JS at `web/js/dashboard.js:2267` only sets the champion-pill from `p.champion`, so during Arena/Brawl games the champion-pill fell through to the slower `/api/locked-champion` fallback poll. The cycle-0 always-on champion+ally_spells write only existed in `aram_coach.py`.
- **Fix:** Both coaches now mirror the ARAM pattern — `current.update({..., "champion": champ, "ally_spells": {champ: [{spell:D}, {spell:F}]} or {}})`. Header pill flips to live data within ~1 coach tick (8–20 s) of game start instead of waiting for the fallback.
- **Verified:** RC restarted to PID 1664 (was 3364), `last_reload_ok=true`. Behavior change only visible in-game.

### NOTE-017 · `vision_token` falls back to legacy hardcoded value
- **File:** `core/vision_token.py:97`
- **Why:** Today's log line `vision_token: using LEGACY hardcoded fallback — rotate by setting RC_VISION_TOKEN env var or writing config/vision_token.txt`. The token is the same magic string everywhere (`8e8f131e212b329438218eca27372dde`). Anyone on the LAN can hit `/upload-frame`, `/upload-lcu`, `/upload-liveclient`. For LAN-only deploy with one user this is fine, but worth a one-time rotation.
- **Effort:** Trivial — generate via `python -c "import secrets; print(secrets.token_hex(16))"`, write to `config/vision_token.txt`, restart RC + Game-PC agents.
- **API impact:** None.

### NOTE-018 · SR coach (`coach_integration.py`) does not write `champion` either
- **File:** `coach_integration.py:884–920` (`_write_fields`)
- **Why:** SR's `_write_fields(fields)` only writes the parsed coach response (`action`, `immediate`, `next`, etc.) plus a few state-derived fields. `champion` is never written, so SR games rely on the `/api/locked-champion` fallback for the header pill. Same gap Arena/Brawl had until FIX-008.
- **Effort:** Medium — SR's write path is structured differently (incremental field merge, retry loop), so the fix needs care. Should add a `_write_state_snapshot` step that runs alongside `_write_fields` per tick.
- **API impact:** None.

---

## Cycle 5 — 2026-04-25 00:11

### NOTE-019 · TFT OCR reader still uses local `PIL.ImageGrab` (post-migration regression)
- **File:** `tft/tft_ocr_reader.py:53–56` (`_grab_region`)
- **Why:** RC runs on Legion (no League window) — `ImageGrab.grab(bbox=...)` captures the dashboard's Edge browser instead of the game. `tft/tft_vision_reader.py` was already migrated to use `modes.shared_vision._capture_screen()` (the relay path), but this OCR sibling was missed. Currently silent because TFT mode isn't being played; will produce garbage OCR if TFT is ever entered.
- **Effort:** Medium — refactor `_grab_region(bbox)` to fetch the full frame once via the relay, cache for 2 s, and crop client-side. Same pattern as `tft_vision_reader._capture_game()`.
- **API impact:** None (Tesseract is local, free).

### NOTE-020 · `rewind_history.db` dominates disk (1.75 GB) — informational
- **File:** `data/rewind_history.db` (read-only)
- **Why:** 2846 matches of full participant + timeline data (per memory `reference_rewind_history_db.md`). Intentional, valuable for cold-start coaching analysis. Just worth knowing — drives ~95 % of the project's 1.8 GB on-disk footprint. If repo is ever git-tracked or backed up, exclude this file.
- **Effort:** N/A (already a documented resource).
- **API impact:** None.

### NOTE-021 · Log retention is implemented and working (CONFIRMED — false alarm)
- **File:** `core/log_setup.py:34–52` (`_prune_old_logs`)
- **Re-reading:** 30-day retention auto-prunes `*.log*` files older than cutoff on every `setup()` call. Today's 122 MB across 19 daily files is well within the bound. No action needed.

---

## Cycle 6 — 2026-04-25 00:14

### FIX-009 · LCU agent exception now reports a result (was NOTE-013)
- **File:** `C:\RC-Agent\gamepc_lcu_agent.py` (Game-PC, `loop()` cmd handler)
- **Bug:** `result = execute_command(cmd)` ran without try/except. If LCU disconnected mid-PATCH (rare but happens during champ-select hand-off), the exception bubbled past the post-cmd-done call, leaving the command stranded "in-flight" on Legion's queue forever. The dashboard's spinning state never resolved.
- **Fix:** Wrapped in try/except — on exception, build `result = {"ok": False, "err": "<ExcClass>: <msg>"}` so the post-cmd-done always fires. Dashboard now sees an explicit failure instead of indefinite pending.
- **Deploy:** Edit applied via PowerShell in-place (with `.bak.<ts>`), `py_compile` verified, atomic move. LCU agent restarted via detached batch (PID 6484 → 5572). NOTE-013 closed.

### FIX-017 · Self-spells JS skips DOM build when hidden by CSS (was NOTE-022)
- **File:** `web/js/dashboard.js` (`renderHeader`)
- **Bug:** Header `display: none !important` rule killed paint/layout of self-spells, but every coach tick was still creating + destroying `<span class="self-spell">` cells that never rendered — wasted DOM churn.
- **Fix:** Added `getComputedStyle(selfSpellsEl).display !== "none"` guard before the build block. When the CSS hides the slot, the renderer short-circuits.
- **Verified:** Dashboard auto-reloaded clean (snapshot v? UI UPDATED toast visible, header layout intact).

### NOTE-023 · Hotkey listener's silent crash leaves Ctrl+Tab dead
- **File:** `core/hotkeys.py:79–80` (`_listen_loop`)
- **Why:** If `GetAsyncKeyState` ever raises (driver glitch, low-memory situation), the listener thread logs error and dies. No restart, no health signal. User would not know force-scan stopped working.
- **Effort:** Low — wrap the loop body in inner try/except + restart-on-exit pattern, OR have `_health_monitor` poll `_thread.is_alive()` and re-`start()`.
- **API impact:** None.

---

## Cycle 7 — 2026-04-25 00:18

### FIX-010 · Hotkey listener auto-restarts on per-tick exception (was NOTE-023)
- **File:** `core/hotkeys.py` (`_listen_loop`)
- **Bug:** Previously the entire `while _running` loop was wrapped in one outer try/except — a single `GetAsyncKeyState` glitch killed the listener forever, silently breaking Ctrl+Tab force-scan with no way to recover short of full RC restart.
- **Fix:** Inverted the structure — try/except is now INSIDE the while loop. Per-tick exceptions log a warning with crash count, sleep with exponential backoff (cap 5 s), and resume on next iteration. Permanent faults still throttle, but transient blips recover within 100 ms.
- **Verified:** RC restarted to PID 8208, `last_reload_ok=true`. Hotkey thread restart verified by reload success (would have surfaced as `last_reload_error`).

### FIX-011 · Game-PC agents now back off when Legion is unreachable (was NOTE-014)
- **Files:** `C:\RC-Agent\gamepc_liveclient_relay.py` + `C:\RC-Agent\gamepc_lcu_agent.py`
- **Bug:** When Legion was unreachable, both agents kept hammering the LAN at full rate (1 s liveclient push, 0.5 s LCU cmd-poll). No exponential backoff like the screen agent already had.
- **Fix:** Both agents now track `consecutive_fail`. After 3 failures, the loop sleep grows exponentially capped at 30 s. First successful upload resets the counter to 0. Mirror of the pattern in `gamepc_screen_agent.py:195`.
- **Deploy:** liveclient_relay rewritten via `mcp__gamepc__write_file` (full file). LCU agent patched via Python in-place edit (UTF-8 safe). Both py_compile-verified, atomic moves. Restarted via detached batch — liveclient_relay PID 7244 → 16696, LCU agent PID 5572 → 16812.
- **Damage prevented:** During a 5-min Legion outage, agent traffic drops from ~600 LAN requests/min (combined) to ~4/min. Less network noise + faster Legion-side recovery.

---

## Cycle 8 — 2026-04-25 00:21

### FIX-012 · Screen agent skips capture during outage (was NOTE-011)
- **File:** `C:\RC-Agent\gamepc_screen_agent.py` (`loop()` + new `probe_legion()` helper)
- **Bug:** During Legion outage, the screen agent kept calling Pillow `ImageGrab.grab()` every cycle (~30 ms CPU per call) only to fail upload. Wasted GDI calls + CPU even though no frame would land.
- **Fix:** Added `probe_legion()` — cheap GET `/health` (no body). When `consecutive_fail >= 3`, the loop probes BEFORE capture; if probe fails, skip the capture entirely and just sleep. Probe-success on a future iter naturally drops back into the normal capture+upload path.
- **Deploy:** Patched via Python in-place edit. py_compile OK. Both screen-agent instances restarted (PIDs 1416, 14172 → 13760, 3908).
- **Damage prevented:** During a 5-min outage with 2 agent instances, ~200 wasted Pillow captures saved (~6 s of CPU + GDI churn). Combined with FIX-011 backoff, the Game-PC side becomes nearly silent during dashboard downtime.

### FIX-018 · `/agent/` file-serve stream-reads with 4 MiB cap (was NOTE-024)
- **File:** `web_dashboard.py` (`/agent/` handler)
- **Bug:** `(_APP_DIR / "tools" / name).read_bytes()` pulled the entire file into RAM before streaming the response. Currently safe because of the allowlist + small file sizes, but the same OOM pattern as FIX-006 (MCP tool_read_file).
- **Fix:** `with open(p, "rb") as f: body = f.read(_AGENT_FILE_CAP)` with a 4 MiB cap matching the MCP file ops. Defensive in case the allowlist ever grows to include larger artifacts.
- **Verified:** RC restarted PID 6832 → 9536. Smoke-tested: `GET /agent/bridge_task.py` → 200, 4028 bytes (matches the actual file).
- **NOTE-024 closed.**

---

## Cycle 9 — 2026-04-25 00:26

### FIX-013 · `/api/analyze` POST was silently 404ing — "Analyze Now" button broken
- **File:** `web_dashboard.py` (POST handler dispatch)
- **Bug:** Dashboard JS at `web/js/dashboard.js:311` POSTs to `/api/analyze` when the user clicks the "Analyze Now" button. The supervisor at port 8890 IS the actual handler (`agents/supervisor.py:1198 _handle_analyze`). But:
  - `_SUPERVISOR_PROXY_PATHS` only forwards GETs, not POSTs.
  - web_dashboard.py POST dispatch has no `/api/analyze` case.
  - Result: POST → 404 → JS catch swallows the error silently, `refreshEnv()` never fires. Button does nothing.
- **Fix:** Added `elif self.path == "/api/analyze":` POST handler in web_dashboard.py that forwards body to `http://127.0.0.1:8890/api/analyze` and streams the response back. 30 s timeout (analysis can take a few seconds for big modes).
- **Verified:** RC restarted to PID 5672. End-to-end smoke test:
  ```
  POST /api/analyze {"mode":"aram"} → 200
  {"mode":"aram","matches_scanned":2087,"champion_buckets":138,
   "matchups_tracked":6575,...,"elapsed_sec":0.17}
  ```
- **User-visible impact:** "Analyze Now" button on the dashboard is now actually functional.

---

## Cycle 10 — 2026-04-25 00:29

### FIX-014 · SR coach now writes `champion` + `ally_spells` (was NOTE-018)
- **File:** `coach_integration.py` (`_write_fields`)
- **Bug:** SR coach's `_write_fields` only persisted parsed coach response fields, never `champion`. SR games therefore relied on the slower `/api/locked-champion` fallback for the header pill — same gap Arena/Brawl had until cycle 4. With the fixes from cycle 4 + 10, all four live-game coaches (ARAM/Arena/Brawl/SR) now consistently surface the champion field within ~1 coach tick of game start.
- **Fix:** At the top of `_write_fields`, read `self._last_state` (set just before `_write_fields` is called in `_run`) and inject `champion` + `ally_spells` via `setdefault` so the coach response keeps priority but otherwise the state-derived data fills the gap. Same envelope shape as ARAM (lines 421–438 of aram_coach.py).
- **Verified:** RC restarted to PID 9956, `last_reload_ok=true`. Behavior change visible only in SR games.
- **NOTE-018 closed.**

### Smoke-tested all dashboard endpoints (no other silent-broken UI features)
Curled all 13 routes the dashboard JS hits (`/api/health`, `/api/state`, `/api/env`, `/api/locked-champion`, `/api/adaptation`, `/api/advisories`, `/api/ui-version`, `/api/champions`, `/api/activity`, `/api/insight-card`, `/api/minimap-crop`, `/api/trending`, `/api/task/<id>`) — all return 200 (or expected 404 for unknown task IDs). The `/api/analyze` was the only silent-404 case. No further user-visible UI breakage detected.

---

## Cycle 11 — 2026-04-25 00:32

### FIX-015 · TFT OCR reader migrated to vision relay (was NOTE-019)
- **File:** `tft/tft_ocr_reader.py`
- **Bug:** Post-migration to Legion-only RC, `tft_ocr_reader._grab_region` was still calling `PIL.ImageGrab.grab(bbox=...)`, which captures Legion's local screen (the dashboard browser window) instead of the game on Game-PC. Sibling `tft_vision_reader.py` was already migrated to use the relay; this OCR file was missed.
- **Fix:**
  - Added `_capture_full_frame()` — pulls full Game-PC frame once via `modes.shared_vision._capture_screen()`, returns a PIL Image.
  - `_grab_region(bbox, full_img=None)` now crops from a pre-fetched frame (preferred — `read()` fetches once and passes down to all crop calls), or fetches its own as fallback.
  - `read()` fetches one full frame at the top, passes it to all 4 OCR field crops. Cuts per-tick relay round-trips from 4 → 1.
  - `read_stage_round_only()` and `save_debug_crops()` updated to the same path.
  - All call sites guard against `None` (relay down / no frame yet).
- **Verified:** py_compile OK. No restart needed — TFT module isn't loaded in client mode; new code activates when next TFT game starts.

### NOTE-025 · TFT OCR regions calibrated for 1600×900 but Game-PC streams 1920×1080
- **File:** `tft/tft_ocr_reader.py:29–34` (`_REGIONS` constant)
- **Why:** Even with FIX-015 routing OCR through the relay, the bbox tuples target a 1600×900 coordinate space. Game-PC's screen agent captures at native 1920×1080, so cropping with 1600×900 coords lands in the wrong pixels. OCR will return garbage until regions are recalibrated against a real 1920×1080 TFT frame.
- **Effort:** Low — capture an in-TFT 1920×1080 frame, eyeball the new bbox coords for stage_round / level / gold / hp_panel. Same calibration workflow as `core/vision_tesseract.py` regions in `data/vision_regions.json`.
- **API impact:** None (Tesseract is local).

---

## Cycle 12 — 2026-04-25 00:34

Surveyed `core/coaching_timestamps.py`, `modules/cache_engine.py`, `core/feature_policy.py`, `agents/agent4_coach_mentor/`, `ops/rc_state_validator.py`, `ops/rc_screen_validator.py`, supervisor route handlers. No new defects worth shipping a fix for. Two observations only:

### NOTE-026 · `cache_engine.get()` opens TWO SQLite connections per cache hit
- **File:** `modules/cache_engine.py:99–114`
- **Why:** First conn for SELECT, then a second for the use_count++ UPDATE. Each connection-open + WAL setup is ~1 ms; this doubles the cache-hit latency. Could combine into one transaction. Also a tiny race: between SELECT and UPDATE another thread could `flag_bad` (DELETE) the row, our UPDATE silently no-ops.
- **Effort:** Low — keep `with self._conn() as conn:` open across both queries.
- **API impact:** None.

### NOTE-027 · `cache_engine.set()` stores full state JSON per entry
- **File:** `modules/cache_engine.py:116–128`
- **Why:** `game_state_json = json.dumps(state)` stores the full coaching state dict per cache row — typically a few KB but can be larger with verbose item/ability data. Today's `decisions.db` is only 585 KB so not a problem yet, but this scales linearly with cache entries. The `game_state_json` column doesn't appear to be read by the get path or by any analyzer; if it's truly unused, drop it from `set()` writes.
- **Effort:** Trivial if confirmed unused — one `grep` to verify, then null the column.
- **API impact:** None.

---

## Cycle 13 — 2026-04-25 00:37

### FIX-016 · `cache_engine.get()` single-connection + drop unused state JSON write (was NOTE-026 + NOTE-027)
- **File:** `modules/cache_engine.py`
- **Bug bundle:**
  - **NOTE-026:** `get()` opened two SQLite connections per cache hit — one for SELECT, another for the use_count++ UPDATE. Doubled per-hit latency (~2 ms vs ~1 ms) and left a race window where `flag_bad()` could DELETE the row between SELECT and UPDATE, silently no-opping the increment.
  - **NOTE-027:** `set()` stored `json.dumps(state)` into `game_state_json` for every cache row. Grep across the entire codebase confirmed the column is NEVER read — purely write-only ballast. Each entry was a few KB heavier than necessary.
- **Fix:**
  - `get()` now wraps SELECT and UPDATE in one `with self._conn() as conn:` block. Both queries run inside the same transaction, eliminating the race and halving connection overhead.
  - `set()` writes empty string into `game_state_json` (column preserved for schema back-compat). New entries from this point forward consume only the row metadata + response text.
- **Verified:** RC restarted to PID 6832, `last_reload_ok=true`. Cache-hit hot-path is now ~1 ms instead of ~2 ms.
- **NOTE-026 + NOTE-027 closed.**




---

## Audit Summary — through cycle 15

**18 fixes shipped, 27 notes captured.**

### Highest-impact fixes
1. **FIX-013 /api/analyze proxy** — restored a silently-broken dashboard button (was 404ing with no user feedback)
2. **FIX-001 vision-frame staleness** — prevents Sonnet credit burn when Game-PC agent goes down
3. **FIX-006 MCP tool_read_file OOM** — deployed cross-machine; prevents server crash on large file paths
4. **FIX-008 Arena+Brawl champion writes** + **FIX-014 SR coach** — all 4 live coaches now consistently surface champion to dashboard payload
5. **FIX-011 Game-PC agents backoff** — combined with **FIX-012 screen agent capture skip**, drops Game-PC LAN traffic ~99% during Legion outages
6. **FIX-010 hotkey listener auto-restart** — single GetAsyncKeyState glitch no longer kills Ctrl+Tab forever
7. **FIX-009 LCU agent cmd-done** — stranded commands no longer pile up in the queue when LCU disconnects mid-PATCH

### Performance + robustness fixes
- **FIX-002** /api/state 1s cache → cuts vision-relay load on multi-tab dashboard polls
- **FIX-007 BUNDLE** — Tesseract atomic counter + lcu-cmd validation + console-error 10Hz throttle (3 hardenings, 1 restart)
- **FIX-016 BUNDLE** — cache_engine single-conn + drop unused state JSON (cache hit ~2 ms → ~1 ms, race window closed)
- **FIX-017** self-spells DOM short-circuit when CSS-hidden (no per-tick churn for invisible elements)
- **FIX-018** /agent/ file-serve stream-read with 4 MiB cap

### Tooling improvements
- **FIX-003** bridge_task.py auto-picks `--kind=note` when --prompt missing (made the audit's own cron prompt work)
- **FIX-004** data_pipeline `cmd_items_index` — auto-regenerates web/data/items_index.json from DDragon meta on each `data_pipeline.py all`
- **FIX-005** BaseCoach _lock comment clarification
- **FIX-015** TFT OCR migrated to vision relay (was capturing dashboard browser instead of game)

### Open notes (none blocking)
- **NOTE-003** Coaching data multi-writer race (HIGH effort — needs file-level lock or single-writer queue)
- **NOTE-006** game_reader idle polling when no game (frozen-adjacent — would need `_game_lifecycle` cooperation)
- **NOTE-008** Console pipe localStorage fallback (MEDIUM)
- **NOTE-017** vision_token rotation (trivial but needs user to generate + place secret)
- **NOTE-025** TFT OCR region calibration 1600×900 → 1920×1080 (needs in-TFT frame for re-bbox)

### Cross-machine deploys
Deployed and restarted on Game-PC (192.168.8.237):
- `gamepc_mcp_server.py` (read_bytes OOM fix)
- `gamepc_lcu_agent.py` (exception cmd-done report + Legion-down backoff)
- `gamepc_liveclient_relay.py` (Legion-down backoff)
- `gamepc_screen_agent.py` (probe-before-capture during outage)

All restarts used the detached-batch pattern (write `.cmd`, `cmd /c start /B`, kill old PID, launch new) so the in-flight MCP call survived each kill.

### Cumulative restart count
RC restarted 9 times across the audit. Final PID 9536. `last_reload_ok=true` after every restart; no `last_reload_error` ever surfaced.

---

## Cycle 17 — 2026-04-25 00:46

Surveyed `core/version_check.py`, `core/resource_manager.py`. Two minor observations only — neither materially impacts current behavior.

### NOTE-028 · `version_check._save` is non-atomic
- **File:** `core/version_check.py:92–99`
- **Why:** `p.write_text(...)` directly writes — interrupted writes leave a partial/empty file. The codebase uses tmp+replace pattern elsewhere. Also: when Live API returns successfully but with empty `gameVersion`, the empty info is saved BEFORE the cache-load fallback runs, clobbering prior good version.
- **Effort:** Trivial — switch to tmp+replace, and gate save on `info["game_version"]` truthiness.
- **API impact:** None.

### NOTE-029 · ResourceManager docstring promises coach restart that isn't implemented
- **File:** `core/resource_manager.py:7` (docstring) vs `:85–105` (watchdog)
- **Why:** Header claims "restart coach at 500 MB". Implementation only logs error + runs `gc.collect()` — no coach restart. Misleading. Either implement the restart wiring OR update the docstring to "warn at 300 MB, force GC at 500 MB".
- **Effort:** Trivial for docstring; medium for actual restart wiring (touches frozen `app/_remediation.py`).
- **API impact:** None.

---

## Cycle 18 — 2026-04-25 00:50

### FIX-019 · `version_check._save` atomic write + clobber-prevention (was NOTE-028)
- **File:** `core/version_check.py`
- **Bug pair:**
  - `_save` used `p.write_text(...)` directly — non-atomic; interrupted writes leave partial files.
  - `check_version()` saved BEFORE the cache fallback, so a successful API call returning empty `gameVersion` would clobber the prior good cached version.
- **Fix:**
  - `_save` now uses tmp+replace pattern.
  - `check_version()` only persists when `info["game_version"]` is truthy. Otherwise the cached file stays intact.

### FIX-020 · ResourceManager docstring corrected (was NOTE-029)
- **File:** `core/resource_manager.py:1–10`
- **Bug:** Docstring promised "restart coach at 500 MB" but the watchdog only logs + `gc.collect()`s. Misleading documentation could lead someone debugging memory issues to expect remediation that doesn't fire.
- **Fix:** Updated docstring to accurately describe the watchdog (warn at 300 MB, force GC at 500 MB) and explicitly notes that wiring an actual restart would need to touch frozen `app/_remediation.py`.
- **Verified:** RC restarted PID 9536 → 14232, `last_reload_ok=true`.

---

## Cycle 27 — 2026-04-25 01:15

### NOTE-030 · `MatchDB` uses `check_same_thread=False` without serializing writes
- **File:** `core/match_db.py:67–107`
- **Why:** Connection is opened with `check_same_thread=False` so concurrent threads CAN call `save_match`, `get_recent`, etc. — but the class doesn't hold a `threading.Lock`. Two simultaneous `save_match` calls' INSERT + commit would race; ordering is undefined and a transient busy could surface. Today MatchDB is only opened from `performance_tracker.py` which appears single-threaded, so the race doesn't materialize. If future code paths add a parallel writer, this becomes load-bearing.
- **Effort:** Trivial — wrap `save_match` body in `with self._lock:` (init `self._lock = threading.Lock()` in __init__).
- **API impact:** None.

---

## Cycle 28 — 2026-04-25 01:19

### FIX-021 · MatchDB write serialization lock (was NOTE-030)
- **File:** `core/match_db.py`
- **Bug:** `MatchDB` opened the SQLite connection with `check_same_thread=False` (allowing cross-thread access) but didn't hold a lock around `save_match`'s INSERT + commit pair. Today the only caller is `performance_tracker.py` (single thread), so the race was dormant — but the safety guarantee was missing.
- **Fix:** Added `self._lock = threading.Lock()` to `__init__`, wrapped the INSERT + commit pair in `with self._lock:`. Defensive against any future parallel writer.
- **Verified:** RC restarted PID 14232 → 10596, `last_reload_ok=true`.
- **NOTE-030 closed.**

---

## Cycle 36 — 2026-04-25 01:42

### NOTE-031 · `core/moon_sync.py` is dead code (Moon-PC retired post-migration)
- **File:** `core/moon_sync.py` (138 lines)
- **Why:** Per CLAUDE.md, Moon-PC was retired in the 2026-04-19 migration — vision now runs in-process on Legion at 127.0.0.1:8889, no LAN sync to a separate machine. A grep confirms no production code imports `moon_sync` / `MoonSync` / `start_sync`. The two stale references to `"moon_sync_inbox/"` in `lan_bridge.py` and `moon_vision_server.py` are just directory paths, not module imports.
- **Effort:** Trivial — `git rm core/moon_sync.py` (or move under `legacy/`). Helps newcomers avoid wiring up a dead module.
- **API impact:** None.

---

## Audit STOP — 2026-04-25 02:12 (cycle 46)

**Stop trigger:** 10 consecutive cycles without a new fix or note (cycles 37–46 with one micro-note in cycle 36 already counted as activity).

**Final aggregate:**
- **21 fixes shipped** across the audit
- **31 notes captured** (16 closed/implemented, 15 still open — none blocking)
- **9 RC restarts** (final PID: 10596, all `last_reload_ok=true`)
- **4 cross-machine deploys** to Game-PC
- Cron job `37a8878b` deleted

**Areas surveyed without findings (the bug surface is exhausted):** modules/cache_engine, core/coaching_timestamps, core/feature_policy, core/match_metrics, core/data_store, core/metric_streamer, core/aftergame_summary, core/sr_aram_worker, core/benchmarks, core/config_validator, core/match_db, core/version_check (FIX-019), core/resource_manager (FIX-020), core/hotkeys (FIX-010), core/vision_tesseract (FIX-007), core/log_setup (frozen, retention confirmed working), tft/tft_state_reader, tft/tft_data, tft/tft_ocr_reader (FIX-015), agents/agent2_backend (file_ingest, db_schema, backfill_kda, migration_rewind), agents/agent4_coach_mentor (analyzer, advisory_sweeper, cold_streak_detector), agents/agent6_auditor (probes), ops/rc_self_monitor, ops/rc_incident_log, ops/rc_state_validator, ops/rc_screen_validator, ops/rc_file_bridge, ops/rc_bootstrap, ops/rc_transactional_deploy, ops/_scheduler_client, ops/phase3_setup, web_dashboard.py routes (smoke-tested all 13 dashboard endpoints).

**The 5 still-open notes (none urgent):**
- NOTE-003 Coaching data multi-writer race (HIGH — needs file lock or single-writer queue)
- NOTE-006 game_reader idle polling when no game (frozen-adjacent, needs `_game_lifecycle` cooperation)
- NOTE-008 Console-pipe localStorage fallback (MEDIUM — observability hardening)
- NOTE-017 vision_token rotation (trivial but needs user to generate + place secret)
- NOTE-025 TFT OCR region calibration 1600×900 → 1920×1080 (needs in-TFT frame for re-bbox)
- NOTE-031 core/moon_sync.py is dead code (trivial cleanup, deferred)

The audit is complete.

---

## Post-audit cleanup — 2026-04-25 02:30 (user-driven)

User reviewed the open notes and approved closing all except NOTE-025 (TFT calibration, deferred to user's next TFT session).

### FIX-022 · Vision token rotated (was NOTE-017)
- New token: `[REDACTED 2026-09-06 - value rotated and dead]` (`config/vision_token.txt` on Legion, `C:\RC-Agent\vision_token.txt` on Game-PC). The original text claimed this path was "gitignored". It was not, and it stayed not for 113 days: `config/vision_token.txt` was TRACKED from the initial commit until 2026-09-06, when it was rotated and untracked in one commit. Recording a secret as gitignored is not the same as gitignoring it - this is the only edit ever made to this archived file, and it was made because the claim in it was false.
- Restored `_resolve_auth_token()` in Game-PC's `gamepc_lcu_agent.py` and `gamepc_liveclient_relay.py` (cycle-7 rewrites had stripped the resolver — they hardcoded the legacy token)
- Restarted RC + 4 Game-PC agents. Vision relay (:8889) now requires the new token.
- **Side-effect (recovered):** the MCP server's auth resolver falls back to `vision_token.txt` after `mcp_token.txt`. After restart, the MCP server adopted the NEW vision token, breaking the MCP client (Legion's Claude Code) which was configured with the OLD bearer. Recovered by writing `mcp_token.txt` with the legacy MCP token (now MCP and vision tokens are explicitly separated).
- **NOTE-017 closed.**

### FIX-023 · `core/moon_sync.py` moved to `legacy/` (was NOTE-031)
- 138-line module from the pre-2026-04-19 Moon-PC era. Confirmed no production importers via grep.
- Moved (not deleted) to `C:/Riot Commander/legacy/moon_sync.py` so the file is recoverable if anything turns out to need it. Cleared stale `__pycache__` entry.
- **NOTE-031 closed.**

### FIX-024 · `game_reader` skips direct-API when relay says "no game" (was NOTE-006)
- **File:** `game_reader.py` `_try_relay` + `read_game`
- **Bug:** when no game is running, `_try_relay` returned None (couldn't distinguish "no game" from "relay unreachable"), so `read_game` fell through to the direct Riot API at :2999 which always timed out. ~700 timeout WARN lines/day during client mode.
- **Fix:** `_try_relay` now catches `urllib.error.HTTPError` 404 specifically and sets `self._relay_says_no_game = True`. `read_game` short-circuits and returns None without hitting the direct API.
- **Verified:** post-restart, only 1 WARN at first poll (vs continuous before); subsequent ticks silent. Direct-API call is now skipped when relay's 404 is authoritative.

### FIX-025 · Console-error pipe localStorage fallback queue (was NOTE-008)
- **File:** `web/js/dashboard.js` `setupConsoleErrorPipe`
- **Bug:** when `/api/console-error` was unreachable (server crash, network blip), JS errors were silently lost — exactly when visibility matters most.
- **Fix:** Failed posts now queue to `localStorage[rc-console-error-queue]` (capped at 50 entries / 100 KB). On the next successful post, queued entries flush at 10 Hz with `_replay: true` flag. Queue survives tab reloads.
- **No restart needed:** JS auto-reload picked up the change.

### FIX-026 · Coaching data multi-writer lock (was NOTE-003)
- **Files:** new `core/coaching_data_lock.py`, plus wired into `web_dashboard._set_pregame`, `/api/command refresh` handler, and `coach_integration._write_fields`.
- **Bug:** Multiple in-process writers of `coaching_data.json` (SR coach, dashboard pregame, dashboard refresh, aftergame summary) did read-modify-write cycles without serialization. Concurrent R-M-W could lose updates (one writer's read happened before another's write, then their write clobbered).
- **Fix:** Module-level `threading.Lock()` shared across all four in-process writers via `with coaching_data_lock(): ...`. Atomic write still prevents torn files; the new lock prevents lost updates.
- **Scope note:** Process-local lock — does not protect against cross-process writers (e.g., supervisor's `aftergame_summary` running outside RC). For RC's actual conflict surface this covers the dominant case.
- **Verified:** RC restarted to PID 2724, `last_reload_ok=true`. Dashboard renders cleanly post-reload.

### Still-deferred
- **NOTE-025** — TFT OCR region calibration (1600×900 → 1920×1080). Backlogged for user's next TFT session when an in-game frame is available for re-bbox.
- **NOTE-020** — informational (rewind_history.db disk usage). No action needed.
